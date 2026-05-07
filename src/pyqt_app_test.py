# pyqt_app.py
import warnings
from datetime import date
import sys
import requests
import pandas as pd
import matplotlib
matplotlib.use('QtAgg')  # Must be set before importing pyplot or any backend
import json
import os
from matplotlib.figure import Figure

# Lazy imports: defer Qt-dependent matplotlib pieces until QApplication exists
def _get_canvas_class():
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    class ScrollFriendlyCanvas(FigureCanvasQTAgg):
        """Canvas that ignores wheel events so the parent QScrollArea can scroll."""
        def wheelEvent(self, event):
            event.ignore()
    return ScrollFriendlyCanvas

def _get_plt():
    import matplotlib.pyplot as plt
    return plt


def get_config_path(filename):
    """Return the path to an editable config file.

    - macOS (packaged) : ~/Library/Application Support/ClinicalTrialVisualization/
                         This is the standard macOS location and is immune to
                         App Translocation (macOS security sandbox for downloaded apps).
    - Windows/Linux    : next to the executable
    - Development      : same directory as this source file (src/)
    """
    if getattr(sys, 'frozen', False):
        if sys.platform == 'darwin':
            config_dir = os.path.join(
                os.path.expanduser('~'), 'Library', 'Application Support',
                'ClinicalTrialVisualization'
            )
            os.makedirs(config_dir, exist_ok=True)
            return os.path.join(config_dir, filename)
        # Windows / Linux: next to the executable
        return os.path.join(os.path.dirname(sys.executable), filename)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QTabWidget, QLabel, QLineEdit, 
                            QPushButton, QCheckBox, QScrollArea, QMessageBox,
                            QFrame, QSizePolicy, QSlider, QSpinBox, QSplitter,
                            QDialog)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QFont, QCursor
import numpy as np
import plotly.graph_objects as go
import plotly.io as pio

def process_participant_flow_data(data):
    """
    Process REDCap data based on simplified codebook to create flow counts
    """
    # Initialize counters
    flow_counts = {
        'Consented': 0,
        'Screen_Fail': 0,
        'Screen_Pending': 0,
        'Dropout_Pre_Screen': 0,
        'Lost_FU_Pre_Screen': 0,
        'Screen_Pass': 0,
        'On_Study': 0,
        'Lost_FU_Pre_On_Study': 0,
        'Dropout_Pre_On_Study': 0,
        'Dropout_On_Study': 0,
        'Lost_FU_On_Study': 0,
        'Withdrawn_On_Study': 0,
        'Completed': 0,
        'No_Screen_Status': 0,
        'Date': date.today().strftime('%Y-%m-%d'),
        'Study_Goal': 100  # Default goal, can be configured per study
    }
    
    for record in data:
        # Count consented participants
        if record.get('consent_status') == '1':
            flow_counts['Consented'] += 1
            
            screen_status = record.get('screen_status', '')
            
            if screen_status == '1':  # Screen Pending
                flow_counts['Screen_Pending'] += 1
                screen_pending_status = record.get('screen_pending_status', '')
                if screen_pending_status == '1':
                    flow_counts['Dropout_Pre_Screen'] += 1
                elif screen_pending_status == '2':
                    flow_counts['Lost_FU_Pre_Screen'] += 1
                    
            elif screen_status == '2':  # Screen Pass
                flow_counts['Screen_Pass'] += 1
                screen_pass_status = record.get('screen_pass_status', '')
                
                if screen_pass_status == '1':  # On Study/Active
                    flow_counts['On_Study'] += 1
                    on_study_status = record.get('on_study_status', '')
                    if on_study_status == '1':
                        flow_counts['Dropout_On_Study'] += 1
                    elif on_study_status == '2':
                        flow_counts['Lost_FU_On_Study'] += 1
                    elif on_study_status == '3':
                        flow_counts['Withdrawn_On_Study'] += 1
                    elif on_study_status == '4':
                        flow_counts['Completed'] += 1
                        
                elif screen_pass_status == '2':
                    flow_counts['Lost_FU_Pre_On_Study'] += 1
                elif screen_pass_status == '3':
                    flow_counts['Dropout_Pre_On_Study'] += 1
                    
            elif screen_status == '3':  # Screen Fail
                flow_counts['Screen_Fail'] += 1
            else:  # Consented but no screen status assigned yet
                flow_counts['No_Screen_Status'] += 1
    
    return flow_counts

def create_sankey_data(flow_data):
    """Create source, target, and value arrays for Sankey diagram"""
    # Define nodes (each stage in the flow)
    labels = [
        "Consented",                          # 0
        "Screen Fail",                        # 1
        "Screen Pending",                     # 2
        "Screen Pass",                        # 3
        "Dropout (Pre-Screen)",               # 4
        "Lost FU (Pre-Screen)",               # 5
        "On Study",                           # 6
        "Lost FU (Pre-On Study)",             # 7
        "Dropout (Pre-On Study)",             # 8
        "Dropout (On Study)",                 # 9
        "Lost FU (On Study)",                 # 10
        "Withdrawn (On Study)",               # 11
        "Completed"                           # 12
    ]

    source = []
    target = []
    value = []

    # From Consented to initial outcomes
    if flow_data['Screen_Fail'] > 0:
        source.append(0)
        target.append(1)
        value.append(flow_data['Screen_Fail'])

    if flow_data['Screen_Pending'] > 0:
        source.append(0)
        target.append(2)
        value.append(flow_data['Screen_Pending'])

    if flow_data['Screen_Pass'] > 0:
        source.append(0)
        target.append(3)
        value.append(flow_data['Screen_Pass'])

    # From Screen Pending to dropouts
    if flow_data['Dropout_Pre_Screen'] > 0:
        source.append(2)
        target.append(4)
        value.append(flow_data['Dropout_Pre_Screen'])

    if flow_data['Lost_FU_Pre_Screen'] > 0:
        source.append(2)
        target.append(5)
        value.append(flow_data['Lost_FU_Pre_Screen'])

    # From Screen Pass to next stages
    if flow_data['On_Study'] > 0:
        source.append(3)
        target.append(6)
        value.append(flow_data['On_Study'])

    if flow_data['Lost_FU_Pre_On_Study'] > 0:
        source.append(3)
        target.append(7)
        value.append(flow_data['Lost_FU_Pre_On_Study'])

    if flow_data['Dropout_Pre_On_Study'] > 0:
        source.append(3)
        target.append(8)
        value.append(flow_data['Dropout_Pre_On_Study'])

    # From On Study to final outcomes
    if flow_data['Dropout_On_Study'] > 0:
        source.append(6)
        target.append(9)
        value.append(flow_data['Dropout_On_Study'])

    if flow_data['Lost_FU_On_Study'] > 0:
        source.append(6)
        target.append(10)
        value.append(flow_data['Lost_FU_On_Study'])

    if flow_data['Withdrawn_On_Study'] > 0:
        source.append(6)
        target.append(11)
        value.append(flow_data['Withdrawn_On_Study'])

    if flow_data['Completed'] > 0:
        source.append(6)
        target.append(12)
        value.append(flow_data['Completed'])

    return labels, source, target, value

class DataFetcher(QThread):
    """Thread for fetching data to prevent GUI freezing"""
    data_fetched = Signal(object, str)  # data, study_name
    error_occurred = Signal(str)
    
    def __init__(self, api_key, study_name):
        super().__init__()
        self.api_key = api_key
        self.study_name = study_name
        # Remove the deleteLater connection - we'll handle cleanup manually
    
    def run(self):
        try:
            data = self.fetch_data(self.api_key, self.study_name) # fetches the api data
            self.data_fetched.emit(data, self.study_name) # returns the data and the study name to the main thread
        except Exception as e:
            self.error_occurred.emit(str(e))
    
    def get_study_config(self, study_name):
        """Define what fields to visualize for each study"""
        configs = {
            "CORE Database": {
                "chart_type": "single",
                "fields": ["yesno"],
                "chart_title": "Yes/No Distribution",
                "field_mappings": {
                    "yesno": {
                        "1": "Yes",
                        "0": "No"
                    }
                }
            },
            "Humanity Neurotech": {
                "chart_type": "dual",
                "fields": ["research_enrollment_status___1", "research_enrollment_status___2", "enrolled_patient_status"],
                "chart_titles": ["Research Enrollment Status", "Enrolled Patient Status"]
            },
            "PACS Cortisol Study": {
                "chart_type": "dual",
                "fields": ["research_enrollment_status___1", "research_enrollment_status___2", "enrolled_patient_status"],
                "chart_titles": ["Research Enrollment Status", "Enrolled Patient Status"]
            },
            "default": {
                "chart_type": "sankey_flow",
                "fields": ["consent_status", "screen_status", "screen_pending_status",
                          "screen_pass_date", "screen_pass_status", "on_study_status"],
                "chart_title": "Patient Flow Analysis"
            }
        }
        return configs.get(study_name, configs["default"])

    def fetch_data(self, api_key, study_name):
        # Get study configuration
        config = self.get_study_config(study_name)
        
        # Step 1: Get all record IDs only
        count_data = {
            'token': api_key,
            'content': 'record',
            'action': 'export',
            'format': 'json',
            'type': 'flat',
            'fields[0]': 'record_id',
            'rawOrLabel': 'raw',
            'rawOrLabelHeaders': 'raw',
            'exportCheckboxLabel': 'false',
            'exportSurveyFields': 'false',
            'exportDataAccessGroups': 'false',
            'returnFormat': 'json'
        }
        
        count_response = requests.post('https://redcap.mountsinai.org/redcap/api/', data=count_data)
        
        if count_response.status_code != 200:
            raise Exception(f"Error fetching record IDs: {count_response.status_code}")

        # Parse response and get unique record IDs
        records = count_response.json()
        record_ids_raw = [record['record_id'] for record in records]
        
        try:
            unique_record_ids = list(set([int(rid) for rid in record_ids_raw if rid]))
            unique_record_ids.sort()
        except ValueError:
            unique_record_ids = sorted(list(set(record_ids_raw)))
        
        if not unique_record_ids:
            raise Exception("No valid record IDs found")
        
        # Step 2: Get the actual data for these specific record IDs
        data_request = {
            'token': api_key,
            'content': 'record',
            'action': 'export',
            'format': 'json',
            'type': 'flat',
            'csvDelimiter': '',
            'rawOrLabel': 'raw',
            'rawOrLabelHeaders': 'raw',
            'exportCheckboxLabel': 'True',
            'exportSurveyFields': 'false',
            'exportDataAccessGroups': 'false',
            'returnFormat': 'json'
        }
        
        # Add specific fields based on study configuration
        if config["chart_type"] == "single":
            data_request['fields[0]'] = 'record_id'
            for i, field in enumerate(config["fields"]):
                data_request[f'fields[{i+1}]'] = field
        elif config["chart_type"] == "sankey_flow":
            data_request['fields[0]'] = 'record_id'
            # Add all the new participant status fields
            new_fields = [
                'consent_status', 'screen_status', 'screen_pending_status',
                'screen_pass_date', 'screen_pass_status', 'on_study_status'
            ]
            for i, field in enumerate(new_fields):
                data_request[f'fields[{i+1}]'] = field
        
        # Add the unique record IDs to the request
        for i, record_id in enumerate(unique_record_ids):
            data_request[f'records[{i}]'] = str(record_id)
        
        data_response = requests.post('https://redcap.mountsinai.org/redcap/api/', data=data_request)
        
        if data_response.status_code == 200:
            data = data_response.json()
            
            # Filter to get only one record per unique record ID
            unique_record_ids_str = [str(rid) for rid in unique_record_ids]
            seen_record_ids = set()
            filtered_data = []
            
            for record in data:
                record_id = record.get('record_id')
                if record_id in unique_record_ids_str and record_id not in seen_record_ids:
                    filtered_data.append(record)
                    seen_record_ids.add(record_id)
            
            return filtered_data
        else:
            raise Exception(f"Error fetching data: {data_response.status_code}")
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QTabWidget, QLabel, QLineEdit, 
                            QPushButton, QCheckBox, QScrollArea, QMessageBox,
                            QFrame, QSizePolicy, QSlider, QSpinBox, QSplitter,
                            QDialog)
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QFont, QCursor

class ResizableChartFrame(QFrame):
    """A resizable frame containing a chart that can be expanded/collapsed"""
    def __init__(self, study_name, parent=None):
        super().__init__(parent)
        self.study_name = study_name
        self.is_collapsed = False
        self.chart_height = 6
        self.chart_width = 18
        
        self.setFrameStyle(QFrame.Box)
        self.setLineWidth(2)
        self.setStyleSheet("""
            QFrame {
                border: 2px solid #cccccc;
                border-radius: 8px;
                margin: 5px;
                background-color: white;
            }
        """)
        
        # Main layout
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)
        
        # Create title bar with controls
        self.setup_title_bar()
        
        # Chart container
        self.chart_container = QWidget()
        self.chart_layout = QVBoxLayout(self.chart_container)
        self.chart_layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.chart_container)
        
    def setup_title_bar(self):
        """Create title bar with study name and controls"""
        title_frame = QFrame()
        title_frame.setFixedHeight(60)
        title_frame.setStyleSheet("""
            QFrame {
                background-color: #e3f2fd;
                border: none;
                border-radius: 5px;
                margin: 0px;
            }
        """)
        
        title_layout = QHBoxLayout(title_frame)
        title_layout.setContentsMargins(10, 5, 10, 5)
        
        # Study name label
        self.title_label = QLabel(self.study_name)
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(12)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet("color: #1976D2; border: none;")
        title_layout.addWidget(self.title_label)
        
        title_layout.addStretch()
        
        # Size controls
        size_label = QLabel("Size:")
        size_label.setStyleSheet("color: #1976D2; border: none; font-weight: bold;")
        title_layout.addWidget(size_label)
        
        # Width control
        width_label = QLabel("W:")
        width_label.setStyleSheet("color: #1976D2; border: none;")
        title_layout.addWidget(width_label)
        
        self.width_spinbox = QSpinBox()
        self.width_spinbox.setMinimum(10)
        self.width_spinbox.setMaximum(30)
        self.width_spinbox.setValue(20)
        self.width_spinbox.setFixedWidth(60)
        self.width_spinbox.valueChanged.connect(self.update_chart_width)
        self.width_spinbox.setStyleSheet("""
            QSpinBox {
                border: 1px solid #2196F3;
                border-radius: 3px;
                padding: 2px;
                background-color: white;
                color: black;
            }
        """)
        title_layout.addWidget(self.width_spinbox)
        
        # Height control
        height_label = QLabel("H:")
        height_label.setStyleSheet("color: #1976D2; border: none;")
        title_layout.addWidget(height_label)
        
        self.height_spinbox = QSpinBox()
        self.height_spinbox.setMinimum(4)
        self.height_spinbox.setMaximum(16)
        self.height_spinbox.setValue(8)
        self.height_spinbox.setFixedWidth(60)
        self.height_spinbox.valueChanged.connect(self.update_chart_height)
        self.height_spinbox.setStyleSheet("""
            QSpinBox {
                border: 1px solid #2196F3;
                border-radius: 3px;
                padding: 2px;
                background-color: white;
                color: black;
            }
        """)
        title_layout.addWidget(self.height_spinbox)
        
        # Collapse/Expand button
        self.collapse_btn = QPushButton("−")
        self.collapse_btn.setFixedSize(25, 25)
        self.collapse_btn.clicked.connect(self.toggle_collapse)
        self.collapse_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 12px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        title_layout.addWidget(self.collapse_btn)
        
        self.layout.addWidget(title_frame)
    
    def update_chart_width(self, value):
        """Update chart width"""
        self.chart_width = value
        if hasattr(self, 'chart_data'):
            self.regenerate_chart()
    
    def update_chart_height(self, value):
        """Update chart height"""
        self.chart_height = value
        if hasattr(self, 'chart_data'):
            self.regenerate_chart()
    
    def toggle_collapse(self):
        """Toggle chart visibility"""
        if self.is_collapsed:
            self.chart_container.show()
            self.collapse_btn.setText("−")
            self.is_collapsed = False
        else:
            self.chart_container.hide()
            self.collapse_btn.setText("+")
            self.is_collapsed = True
    
    def add_chart(self, fig, canvas):
        """Add chart to this frame"""
        # Clear existing chart
        while self.chart_layout.count():
            child = self.chart_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        # Add new chart
        self.chart_layout.addWidget(canvas)
        self.chart_canvas = canvas
    
    def regenerate_chart(self):
        """Regenerate chart with new dimensions"""
        if hasattr(self, 'regenerate_callback'):
            self.regenerate_callback(self.study_name, self.chart_width, self.chart_height)

class ChartWidget(QWidget):
    """Custom widget to display matplotlib charts"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        
        # Storage for chart data and frames
        self.chart_data = {}
        self.chart_frames = {}

        # Recruitment rates dictionary
        self.recruitment_rates = {
            "CORE Database": {
                "target_subjects": 0,
                "start_date": date(2023, 1, 1),
                "current_subjects": float('nan')
            },
            "Antiviral Clinical Trial": {
                "target_subjects": 90,
                "start_date": date(2024, 10, 1),
                "current_subjects": float('nan')
            },
            "Lumbrokinase Clinical Trial": {
                "target_subjects": 120,
                "start_date": date(2024, 10, 9),
                "current_subjects": float('nan')
            },
            "Humanity Neurotech": {
                "target_subjects": 30,
                "start_date": date(2024, 12, 18),
                "current_subjects": float('nan')
            },
            "Sana Lyme": {
                "target_subjects": float('nan'),
                "start_date": float('nan'),
                "current_subjects": float('nan')
            },
            "Sirolimus (Rapamycin) Clinical Trial": {
                "target_subjects": 80,
                "start_date": date(2025, 4, 18),
                "current_subjects": float('nan')
            },
            "PACS Cortisol Study": {
                "target_subjects": float('nan'),
                "start_date": float('nan'),
                "current_subjects": float('nan')
            }
        }

        # Load any additional studies saved via the Add Study dialog
        self._load_study_config()

    def _load_study_config(self):
        """Merge study_config.json entries into recruitment_rates for dynamically added studies."""
        try:
            config_path = get_config_path('study_config.json')
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    saved = json.load(f)
                for study_name, info in saved.items():
                    if study_name not in self.recruitment_rates:
                        start_raw = info.get('start_date')
                        try:
                            start = date.fromisoformat(start_raw) if start_raw else float('nan')
                        except (ValueError, TypeError):
                            start = float('nan')
                        target_raw = info.get('target_subjects')
                        try:
                            target = int(target_raw) if target_raw not in (None, '') else float('nan')
                        except (ValueError, TypeError):
                            target = float('nan')
                        self.recruitment_rates[study_name] = {
                            "target_subjects": target,
                            "start_date": start,
                            "current_subjects": float('nan')
                        }
        except Exception:
            pass  # If file is missing or malformed, silently continue

    def clear_charts(self):
        """Clear all existing charts and reset data"""
        while self.layout.count():
            child = self.layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        self.chart_data = {}
        self.chart_frames = {}
        
    def add_chart(self, data, study_name):
        """Add a new chart for the given study"""
        if not data:
            # Create frame even for no data
            frame = ResizableChartFrame(study_name)
            label = QLabel(f"No data to visualize for {study_name}")
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    color: #666666;
                    padding: 20px;
                }
            """)
            frame.chart_layout.addWidget(label)
            self.layout.addWidget(frame)
            return
        
        # Store data for regeneration
        self.chart_data[study_name] = data
        
        # Create resizable frame
        frame = ResizableChartFrame(study_name)
        frame.chart_data = data
        frame.regenerate_callback = self.regenerate_single_chart
        self.chart_frames[study_name] = frame
        
        # Create the chart
        fig, canvas = self.create_chart_for_study(data, study_name, frame.chart_width, frame.chart_height)
        frame.add_chart(fig, canvas)
        
        self.layout.addWidget(frame)

    def create_chart_for_study(self, data, study_name, width=18, height=6):
        """Create chart with specified dimensions"""
        # Create matplotlib figure with specified sizing
        fig = Figure(figsize=(width, height), dpi=100)
        canvas = _get_canvas_class()(fig)
        
        # Set size policy to allow proper resizing
        canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        canvas.setMinimumHeight(int(height * 80))  # Convert to pixels
        
        config = self.get_study_config(study_name)
        
        # Calculate current subjects based on chart type
        if study_name in self.recruitment_rates:
            current_subjects = 0
            
            # Count subjects by status - updated for new codebook
            for record in data:
                if config["chart_type"] == "sankey_flow":
                    # For new codebook, count active and completed participants
                    screen_pass_status = record.get('screen_pass_status', '')
                    on_study_status = record.get('on_study_status', '')
                    # Count those who reached "On Study" status or completed
                    if screen_pass_status == '1':  # On Study/Active
                        current_subjects += 1
                    elif on_study_status == '4':  # Completed  
                        current_subjects += 1
                else:
                    # Original logic for other studies
                    enrolled_status = record.get('enrolled_patient_status', '')
                    if str(enrolled_status) in ['1', '2']:
                        current_subjects += 1
            
            self.recruitment_rates[study_name]["current_subjects"] = current_subjects

        # Create appropriate chart type
        if config["chart_type"] == "single":
            self.create_single_chart_subplot(fig, data, study_name, config)
        elif config["chart_type"] == "sankey_flow":
            self.create_sankey_flow_subplot(fig, data, study_name)
        else:
            self.create_dual_chart_subplot(fig, data, study_name)

        # Add recruitment rate subplot only for non-sankey charts
        if config["chart_type"] != "sankey_flow":
            self.create_recruitment_subplot(fig, study_name)
        
        return fig, canvas
    
    def regenerate_single_chart(self, study_name, width, height):
        """Regenerate a single chart with new dimensions"""
        if study_name not in self.chart_data:
            return
            
        data = self.chart_data[study_name]
        frame = self.chart_frames[study_name]
        
        # Create new chart with new dimensions
        fig, canvas = self.create_chart_for_study(data, study_name, width, height)
        frame.add_chart(fig, canvas)
    
    def get_study_config(self, study_name):
        """Define what fields to visualize for each study"""
        configs = {
            "CORE Database": {
                "chart_type": "single",
                "fields": ["yesno"],
                "chart_title": "Yes/No Distribution",
                "field_mappings": {
                    "yesno": {
                        "1": "Yes",
                        "0": "No"
                    }
                }
            },
            "Antiviral Clinical Trial": {
                "chart_type": "sankey_flow",
                "fields": ["consent_status", "screen_status", "screen_pending_status", 
                          "screen_pass_date", "screen_pass_status", "on_study_status"],
                "chart_title": "Patient Flow Analysis"
            },
            "Lumbrokinase Clinical Trial": {
                "chart_type": "sankey_flow", 
                "fields": ["consent_status", "screen_status", "screen_pending_status", 
                          "screen_pass_date", "screen_pass_status", "on_study_status"],
                "chart_title": "Patient Flow Analysis"
            },
            "Sirolimus (Rapamycin) Clinical Trial": {
                "chart_type": "sankey_flow",
                "fields": ["consent_status", "screen_status", "screen_pending_status", 
                          "screen_pass_date", "screen_pass_status", "on_study_status"],
                "chart_title": "Patient Flow Analysis"
            },
            "Sana Lyme": {
                "chart_type": "sankey_flow",
                "fields": ["consent_status", "screen_status", "screen_pending_status",
                          "screen_pass_date", "screen_pass_status", "on_study_status"],
                "chart_title": "Patient Flow Analysis"
            },
            "Humanity Neurotech": {
                "chart_type": "dual",
                "fields": ["research_enrollment_status___1", "research_enrollment_status___2", "enrolled_patient_status"],
                "chart_titles": ["Research Enrollment Status", "Enrolled Patient Status"]
            },
            "PACS Cortisol Study": {
                "chart_type": "dual",
                "fields": ["research_enrollment_status___1", "research_enrollment_status___2", "enrolled_patient_status"],
                "chart_titles": ["Research Enrollment Status", "Enrolled Patient Status"]
            },
            "default": {
                "chart_type": "sankey_flow",
                "fields": ["consent_status", "screen_status", "screen_pending_status",
                          "screen_pass_date", "screen_pass_status", "on_study_status"],
                "chart_title": "Patient Flow Analysis"
            }
        }
        return configs.get(study_name, configs["default"])
    
    def create_single_chart_subplot(self, fig, data, study_name, config):
        """Create single chart subplot for studies like CORE Database"""
        field_name = config["fields"][0]
        field_mapping = config["field_mappings"][field_name]
        categories = []
        
        # Process all records
        for record in data:
            field_value = record.get(field_name, '')
            if str(field_value) in field_mapping:
                label = field_mapping[str(field_value)]
            else:
                label = "Unknown"
            categories.append(label)
        
        if not categories:
            return
        
        value_counts = pd.Series(categories).value_counts()
        
        ax = fig.add_subplot(121)
        bars = ax.barh(value_counts.index, value_counts.values, 
                      color=['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728'])
        
        # Add count labels on bars
        for i, (category, count) in enumerate(value_counts.items()):
            ax.text(count + max(value_counts.values) * 0.01, i, str(count), 
                   va='center', ha='left', fontweight='bold')
        
        ax.set_xlabel('Record Count')
        ax.set_ylabel('Categories')
        ax.set_title(f"{config['chart_title']}")
        ax.grid(axis='x', alpha=0.3)
        ax.set_xlim(0, max(value_counts.values) * 1.15)
        
        fig.tight_layout()
    
    def create_dual_chart_subplot(self, fig, data, study_name):
        """Create dual chart subplot for most studies"""
        enrolled_map = {
            "1": "On Study/Active",
            "2": "Completed", 
            "3": "Dropout/Lost to follow up",
            "4": "Screen Fail"
        }

        categories_enrollment = []
        categories_research = []
        
        # Process all records
        for record in data:
            consented_enrolled = record.get('research_enrollment_status___1', '0')
            screen_pass = record.get('research_enrollment_status___2', '0')
            enrolled_status = record.get('enrolled_patient_status', '')

            # Process checkbox logic
            if str(consented_enrolled) == '1' and str(screen_pass) == '1':
                label_enrollment = "Consented/Enrolled & Screen Pass"
            elif str(consented_enrolled) == '1':
                label_enrollment = "Consented/Enrolled"
            elif str(screen_pass) == '1':
                label_enrollment = "Screen Pass"
            else:
                label_enrollment = "No Enrollment Status"

            # Process enrolled patient status
            if str(enrolled_status) in enrolled_map:
                label_research = enrolled_map[str(enrolled_status)]
            else:
                label_research = "No Patient Status"

            categories_enrollment.append(label_enrollment)
            categories_research.append(label_research)

        value_enrollment_counts = pd.Series(categories_enrollment).value_counts()
        value_research_counts = pd.Series(categories_research).value_counts()
        
        ax1 = fig.add_subplot(131)
        ax2 = fig.add_subplot(132)

        # Plot enrollment status
        if not value_enrollment_counts.empty:
            bars1 = ax1.barh(value_enrollment_counts.index, value_enrollment_counts.values, 
                           color=['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728'])
            
            # Add count labels on bars
            for i, (category, count) in enumerate(value_enrollment_counts.items()):
                ax1.text(count + max(value_enrollment_counts.values) * 0.01, i, str(count), 
                       va='center', ha='left', fontweight='bold')
            
            ax1.set_xlabel('Record Count')
            ax1.set_ylabel('Categories')
            ax1.set_title("Research Enrollment Status")
            ax1.grid(axis='x', alpha=0.3)
            ax1.set_xlim(0, max(value_enrollment_counts.values) * 1.15)
        else:
            ax1.text(0.5, 0.5, 'No Enrollment Data', ha='center', va='center', 
                   transform=ax1.transAxes)
            ax1.set_title("Research Enrollment Status")

        # Plot research status
        if not value_research_counts.empty:
            bars2 = ax2.barh(value_research_counts.index, value_research_counts.values,
                           color=['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728'])
            
            # Add count labels on bars
            for i, (category, count) in enumerate(value_research_counts.items()):
                ax2.text(count + max(value_research_counts.values) * 0.01, i, str(count), 
                       va='center', ha='left', fontweight='bold')
            
            ax2.set_xlabel('Record Count')
            ax2.set_ylabel('Categories')
            ax2.set_title("Enrolled Patient Status")
            ax2.grid(axis='x', alpha=0.3)
            ax2.set_xlim(0, max(value_research_counts.values) * 1.15)
        else:
            ax2.text(0.5, 0.5, 'No Patient Status Data', ha='center', va='center',
                   transform=ax2.transAxes)
            ax2.set_title("Enrolled Patient Status")

        fig.tight_layout()

    def create_recruitment_subplot(self, fig, study_name):
        """Create recruitment metrics subplot"""
        # Determine subplot position based on existing layout
        if study_name == "CORE Database":  # Single chart type
            ax = fig.add_subplot(122)
        else:  # Dual chart type
            ax = fig.add_subplot(133)
        
        if study_name not in self.recruitment_rates:
            ax.text(0.5, 0.5, 'No Recruitment Data', ha='center', va='center', 
                   transform=ax.transAxes)
            ax.set_title("Recruitment Metrics")
            return
        
        recruitment_data = self.recruitment_rates[study_name]
        
        # Get recruitment metrics
        current = recruitment_data["current_subjects"]
        target = recruitment_data["target_subjects"]
        start_date = recruitment_data["start_date"]

        # Handle studies with missing data
        if (pd.isna(target) or pd.isna(start_date) or 
            isinstance(target, float) and pd.isna(target) or
            isinstance(start_date, float) and pd.isna(start_date)):
            ax.text(0.5, 0.5, f'Incomplete Recruitment Data\nCurrent Subjects: {current}', 
                   ha='center', va='center', transform=ax.transAxes)
            ax.set_title("Recruitment Metrics")
            return
        
        # Calculate rates
        today = date.today()
        
        # Calculate months since start
        try:
            months = (today.year - start_date.year) * 12 + (today.month - start_date.month)
            if months < 0:  # Future start date
                months = 0
        except AttributeError:
            months = 0
        
        monthly_rate = current / months if months > 0 else 0
        
        # Create metrics data (removed recruitment_rate)
        metrics = [current, target, months, monthly_rate]
        labels = [
            f'Current\nSubjects\n({current})',
            f'Target\nSubjects\n({target})',
            f'Months Since\nStart\n({months})',
            f'Monthly\nRate\n({monthly_rate:.1f}/mo)'
        ]
        
        # Filter out invalid metrics
        valid_metrics = []
        valid_labels = []
        for i, metric in enumerate(metrics):
            if not (pd.isna(metric) or metric == float('inf')):
                valid_metrics.append(metric)
                valid_labels.append(labels[i])
        
        if not valid_metrics:
            ax.text(0.5, 0.5, 'No Valid Metrics to Display', ha='center', va='center', 
                   transform=ax.transAxes)
            ax.set_title("Recruitment Metrics")
            return
        
        # Create bar chart
        colors = ['#2ca02c', '#1f77b4', '#ff7f0e', '#9467bd']
        chart_colors = colors[:len(valid_metrics)]
        
        bars = ax.bar(range(len(valid_metrics)), valid_metrics, color=chart_colors, alpha=0.7)
        
        # Add value labels on bars
        max_metric = max(valid_metrics) if valid_metrics else 1
        for i, (bar, metric) in enumerate(zip(bars, valid_metrics)):
            ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + max_metric * 0.01,
                   f'{metric:.1f}', ha='center', va='bottom', fontweight='bold')
        
        ax.set_xticks(range(len(valid_labels)))
        ax.set_xticklabels(valid_labels, rotation=45, ha='right', fontsize=8)
        ax.set_ylabel('Value')
        ax.set_title('Recruitment Metrics')
        ax.grid(axis='y', alpha=0.3)
        
        fig.tight_layout()

    def create_sankey_flow_subplot(self, fig, data, study_name):
        """Create Sankey diagram and time series for patient flow"""
        # Process data to get flow counts
        flow_data = process_participant_flow_data(data)
        
        # Create Sankey diagram subplot
        ax1 = fig.add_subplot(121)
        self.create_flow_chart(ax1, flow_data, study_name)
        
        # Create time series subplot  
        ax2 = fig.add_subplot(122)
        self.create_time_series_plot(ax2, flow_data, study_name, data)
        
        fig.tight_layout()

    def create_flow_chart(self, ax, flow_data, study_name):
        """Draw a CONSORT-style patient flow diagram using matplotlib patches"""
        from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

        ax.axis('off')
        ax.set_xlim(-6, 12)
        ax.set_ylim(0, 12)
        ax.set_title(f'{study_name}\nPatient Flow (CONSORT)', fontsize=10, fontweight='bold', pad=8)

        fd = flow_data

        # Helper: draw a box with text, returns center (cx, cy)
        def draw_box(cx, cy, w, h, text, facecolor='#ddeeff', edgecolor="#1976D2"):#edgecolor='#1976D2'
            import textwrap
            x = cx - w / 2
            y = cy - h / 2
            box = FancyBboxPatch((x, y), w, h,
                                 boxstyle="round,pad=0.1",
                                 facecolor=facecolor, edgecolor=edgecolor, linewidth=1.5)
            ax.add_patch(box)
            # Wrap each line to fit within the box width.
            # xlim spans 18 units; ~5 chars per data unit at fontsize 7.5 for this layout.
            chars_per_line = max(6, int(w * 5.0))
            raw_lines = text.split('\n')
            wrapped_lines = []
            bold_flags = []
            for j, raw_line in enumerate(raw_lines):
                sub = textwrap.wrap(raw_line.strip(), width=chars_per_line) or [raw_line]
                for s in sub:
                    wrapped_lines.append(s)
                    bold_flags.append(j == 0)  # all segments of the title line stay bold
            n = len(wrapped_lines)
            line_h = h / (n + 1)
            for i, line in enumerate(wrapped_lines):
                offset = ((n - 1) / 2.0 - i) * line_h
                ax.text(cx, cy + offset, line, ha='center', va='center', fontsize=7.5,
                        fontweight='bold' if bold_flags[i] else 'normal')

                

        # Helper: draw a side exclusion box
        def draw_excl_box(cx, cy, w, h, text, edgecolor='#e67e00'):
            draw_box(cx, cy, w, h, text, facecolor='#fff0e0', edgecolor=edgecolor)#e67e00

        # Helper: vertical arrow
        def varrow(cx, y_from, y_to):
            ax.annotate('', xy=(cx, y_to), xytext=(cx, y_from),
                        arrowprops=dict(arrowstyle='->', color='#444444', lw=1.5))

        # Helper: horizontal arrow from main column to side box
        def harrow(x_from, y, x_to):
            ax.annotate('', xy=(x_to, y), xytext=(x_from, y),
                        arrowprops=dict(arrowstyle='->', color='#444444', lw=1.5))
        
        def vline(x, y_from, y_to):
            ax.plot([x, x], [y_from, y_to], color='#444444', lw=1.5)

        def hline(x_from, x_to, y):
            ax.plot([x_from, x_to], [y, y], color='#444444', lw=1.5)

        def branch_down(cx, y_from, y_to):
            """Arrow that starts flush with a hline (no shrink at origin)"""
            ax.annotate('', xy=(cx, y_to), xytext=(cx, y_from),
                        arrowprops=dict(arrowstyle='->', color='#444444', lw=1.5,
                                        shrinkA=0, shrinkB=0))

        # Define box dimensions and positions
        bw, bh = 3.0, 1.0   # main box width/height
        ew, eh = 3.0, 1.0  # exclusion box width/height

        # --- Column positions (left to right) ---        
        center_col_x = 3.0             # main column x center
        left_col_x = center_col_x - ew - 0.5  # left side x center for exclusions
        right_col_x = center_col_x + ew + 0.5 # right side x center for exclusions
        far_left_col_x = left_col_x - ew - 0.5  # far left x center for earlier exclusions
        far_right_col_x = right_col_x + ew + 0.5    # far right x center for later exclusions

        # --- Row positions (top to bottom) ---
        y1 = 11.0   # Consented
        y2 = 9.0   # Screen Pending / Screen Fail / Screen Pass row
        y3 = 7.0   # pre-on-study drops / On Study row
        y4 = 5.0   # On Study drops
        y5 = 3.0   # Completed
        y6 = 1.0   # Time series row (not used in flow chart)

        consented_total = fd['Consented']
        no_status = fd.get('No_Screen_Status', 0)

        screen_pending_total = fd['Screen_Pending']
        screen_pass_total = fd['Screen_Pass']
        screen_fail_total = fd['Screen_Fail']

        Dropouts_Pre_Screen_Total = fd['Dropout_Pre_Screen'] 
        Lost_FU_Pre_Screen_Total = fd['Lost_FU_Pre_Screen']

        Dropouts_Pre_On_Study_Total = fd['Dropout_Pre_On_Study']
        Lost_FU_Pre_On_Study_Total = fd['Lost_FU_Pre_On_Study']

        On_study_total = fd['On_Study']

        Dropout_On_Study_Total = fd['Dropout_On_Study']
        Lost_FU_On_Study_Total = fd['Lost_FU_On_Study']
        Withdrawn_On_Study_Total = fd['Withdrawn_On_Study']

        Completed_total = fd['Completed']


        # Consented
        consented_text = f"Consented\nN = {consented_total}"
        if no_status > 0:
            consented_text += f"\nAwaiting Screen Status: {no_status}"
        draw_box(center_col_x, y1, bw+2.0, bh, consented_text)

        # Screen Pending box
        screen_pending_label = f"Screen Pending\nN = {screen_pending_total}"
        draw_box(center_col_x, y2, bw, bh, screen_pending_label, facecolor="#f7f5a0", edgecolor="#f5d862")

        # Screen Fail box (includes Pre-Screen Dropout and Pre-Screen LFU)
        screen_fail_label = (f"Screen Fail\nN = {screen_fail_total}"
                             f"\nPre-Screen Dropout: {Dropouts_Pre_Screen_Total}"
                             f"\nPre-Screen LFU: {Lost_FU_Pre_Screen_Total}")
        draw_box(far_left_col_x, y2-0.5, bw+0.5, bh + 0.75, screen_fail_label, edgecolor="#f7634f", facecolor="#fcb5b5")

        # Screen Pass Box
        screen_pass_label = f"Screen Pass\nN = {screen_pass_total}"
        draw_box(far_right_col_x, y2, bw, bh, screen_pass_label)

        # # Pre-Screen Dropout Box
        # pre_screen_dropout = f"Pre-Screen Dropout\nN = {Dropouts_Pre_Screen_Total}"
        # draw_excl_box(right_col_x, y3, ew, eh, f"{pre_screen_dropout}")

        # # Pre-Screen LFU Box
        # pre_screen_lfu = f"Pre-Screen LFU\nN = {Lost_FU_Pre_Screen_Total}"
        # draw_excl_box(far_right_col_x, y3, ew, eh, f"{pre_screen_lfu}")

        # Pre-On Study Dropout Box
        pre_on_study_dropout = f"Pre-On Study Dropout\nN = {Dropouts_Pre_On_Study_Total}"
        draw_excl_box(center_col_x, y3, ew, eh, f"{pre_on_study_dropout}")

        # Pre-On Study LFU Box
        pre_on_study_lfu = f"Pre-On Study LFU\nN = {Lost_FU_Pre_On_Study_Total}"
        draw_excl_box(right_col_x, y3, ew, eh, f"{pre_on_study_lfu}")

        # On Study  Box
        on_study_box = f"On Study\nN = {On_study_total}"
        draw_box(far_right_col_x, y4, bw, bh, on_study_box)

        # Dropout On Study Box
        dropout_on_study_box = f"Dropout On Study\nN = {Dropout_On_Study_Total}"
        draw_excl_box(center_col_x, y5, ew, eh, dropout_on_study_box)

        # LFU On Study Box
        lfu_on_study_box = f"LFU On Study\nN = {Lost_FU_On_Study_Total}"
        draw_excl_box(right_col_x, y5, ew, eh, lfu_on_study_box)

        # Withdrawn On Study Box
        withdrawn_on_study_box = f"Withdrawn On Study\nN = {Withdrawn_On_Study_Total}"
        draw_excl_box(left_col_x, y5, ew, eh, withdrawn_on_study_box)

        # Completed Box
        completed_box = f"Completed\nN = {Completed_total}"
        draw_box(far_right_col_x, y6, bw, bh, completed_box, facecolor='#a5d6a7', edgecolor="#388e3c")

        # --- Draw arrows between boxes ---
        # pad matches boxstyle="round,pad=0.1" so lines/arrows start and end
        # at the visual box edge, not inside it.
        pad = 0.1

        # Line from Consented bottom → junction above screening row
        #vline(center_col_x, y1 - bh/2 - pad, y2 + bh)

        # Horizontal bar spanning all three screen columns
        hline(far_left_col_x, far_right_col_x, y2 + bh)

        # Arrows junction → screening boxes
        branch_down(far_left_col_x,  y2 + bh, y2 + bh/2 + pad)  # Screen fail
        branch_down(center_col_x, y1-bh/2 - pad, y2 + bh/2 + pad)  # Screen Pending
        branch_down(far_right_col_x,  y2 + bh, y2 + bh/2 + pad)  # Screen Pass

        # Screen Pending → Pre-Screen Dropout and Pre-Screen LFU
        # hline(right_col_x, far_right_col_x, y3 + eh)
        # branch_down(right_col_x, y3 + eh, y3 + eh/2 + pad)  # Pre-Screen Dropout
        # branch_down(far_right_col_x, y2 - eh/2 - pad, y3 + eh/2 + pad)  # Pre-Screen LFU

        # Screen Pass → Pre-On Study exits and On Study
        hline(far_right_col_x, center_col_x, y3 + eh)
        branch_down(center_col_x, y3 + eh, y3 + eh/2 + pad)  # Pre-On Study Dropout
        branch_down(right_col_x, y3 + eh, y3 + eh/2 + pad)  # Pre-On Study LFU
        varrow(far_right_col_x, y2 - bh/2 - pad, y4 + bh/2 + pad)  # On Study

        # On Study → on-study exits and Completed
        hline(far_right_col_x, left_col_x, y5 + eh)
        branch_down(left_col_x, y5 + eh, y5 + eh/2 + pad)  # Dropout On Study
        branch_down(center_col_x, y5 + eh, y5 + eh/2 + pad)  # LFU On Study
        branch_down(right_col_x, y5 + eh, y5 + eh/2 + pad)  # Withdrawn On Study
        varrow(far_right_col_x, y4 - bh/2 - pad, y6 + bh/2 + pad)  # Completed

    def create_time_series_plot(self, ax, flow_data, study_name, data):
        """Create time series plot showing screen passes by date and current status breakdown"""
        from datetime import timedelta
        import pandas as pd
        from collections import defaultdict
        import matplotlib.dates as mdates
        
        # Extract and process screen pass dates from original data
        screen_pass_dates = []
        for record in data:
            if record.get('screen_status') == '2':  # Screen Pass
                screen_pass_date = record.get('screen_pass_date', '')
                if screen_pass_date and screen_pass_date.strip():  # Non-empty date
                    try:
                        # Parse the date (assuming MM-DD-YYYY or MM/DD/YYYY format)
                        if '-' in screen_pass_date:
                            date_obj = pd.to_datetime(screen_pass_date, format='%m-%d-%Y')
                        elif '/' in screen_pass_date:
                            date_obj = pd.to_datetime(screen_pass_date, format='%m/%d/%Y')
                        else:
                            # Try automatic parsing
                            date_obj = pd.to_datetime(screen_pass_date)
                        screen_pass_dates.append(date_obj)
                    except (ValueError, TypeError):
                        # Skip invalid dates
                        continue
        
        # Create time series if we have valid dates
        if screen_pass_dates:
            # Group by month-year and count
            df_dates = pd.DataFrame({'date': screen_pass_dates})
            df_dates['month_year'] = df_dates['date'].dt.to_period('M')
            monthly_counts = df_dates['month_year'].value_counts().sort_index()
            
            # Convert periods back to timestamps for plotting
            monthly_dates = [period.start_time for period in monthly_counts.index]
            monthly_values = monthly_counts.values
            
            # Create cumulative screen passes over time
            cumulative_values = monthly_values.cumsum()
            
            # Plot the time series
            ax.plot(monthly_dates, cumulative_values, 'o-', 
                   label=f'Cumulative Screen Pass: {cumulative_values[-1] if cumulative_values.size > 0 else 0}', 
                   markersize=6, linewidth=2, color='#2ca02c')
            
            # Add monthly increment bars
            ax.bar(monthly_dates, monthly_values, width=20, alpha=0.3, 
                   label=f'Monthly Screen Pass', color='#2ca02c')
            
            # Add data point labels
            for date, cum_val, monthly_val in zip(monthly_dates, cumulative_values, monthly_values):
                if monthly_val > 0:
                    ax.annotate(f'{monthly_val}', (date, cum_val), 
                               textcoords="offset points", xytext=(0,10), 
                               ha='center', fontsize=8)
            
            # Format x-axis to show months nicely
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
        
        else:
            # No valid screen pass dates - show message
            ax.text(0.5, 0.8, 'No screen pass dates available for time series analysis', 
                   ha='center', va='center', transform=ax.transAxes,
                   bbox=dict(boxstyle="round,pad=0.3", facecolor='lightgray', alpha=0.7))
        
        # Add current status breakdown as stacked bars (keeping the original logic)
        current_date = pd.to_datetime(flow_data['Date'])
        study_goal = flow_data['Study_Goal']
        completed = flow_data['Completed']
        
        # Calculate remaining active (those on study but not completed/dropped)
        active_on_study = max(0, flow_data['On_Study'] - (
            flow_data['Dropout_On_Study'] + flow_data['Lost_FU_On_Study'] + 
            flow_data['Withdrawn_On_Study'] + flow_data['Completed']
        ))
        
        # Plot study goal line (always shown)
        ax.axhline(y=study_goal, color='red', linestyle=':', linewidth=1.5,
                   label=f'Study Goal: {study_goal}', alpha=0.9)
        
        # Create stacked bars for current status breakdown at current date
        bar_width = timedelta(days=0.75)
        bar_x_position = current_date
        
        # Total dropouts (excludes Screen Fail, Pre-Screen Dropout, Pre-Screen LFU)
        total_dropouts = (
            flow_data['Lost_FU_Pre_On_Study'] + flow_data['Dropout_Pre_On_Study'] +
            flow_data['Dropout_On_Study'] + flow_data['Lost_FU_On_Study'] + flow_data['Withdrawn_On_Study']
        )

        # Both bar groups centered around current_date, touching at the date line
        half = timedelta(days=0.375)   # half of bar_width
        active_stack_x = bar_x_position - half   # stacked bar on the left
        completed_x    = bar_x_position + half   # completed bar on the right

        # Active On Study stacked on top of Total Dropouts/Lost FU (left bar)
        if total_dropouts > 0:
            ax.bar(active_stack_x, total_dropouts, width=bar_width,
                   alpha=0.7, label=f'Total Dropouts/Lost FU: {total_dropouts}', color='orange')
        if active_on_study > 0:
            ax.bar(active_stack_x, active_on_study, width=bar_width,
                   bottom=total_dropouts, alpha=0.7,
                   label=f'Active On Study: {active_on_study}', color='blue')

        # Completed participants (right bar)
        if completed > 0:
            ax.bar(completed_x, completed, width=bar_width,
                   alpha=0.7, label=f'Completed: {completed}', color='green')
        
        # Format the plot
        ax.set_ylabel('Patient Count')
        ax.set_title(f'Screen Pass Timeline & Current Status')
        ax.legend(loc='upper left', fontsize=8)
        ax.grid(True, alpha=0.3)
        
        # Set y-axis to show reasonable range
        max_val = max(study_goal, flow_data['Screen_Pass'], completed + active_on_study + total_dropouts) + 5
        ax.set_ylim(0, max_val)
        
        # Format x-axis
        ax.tick_params(axis='x', rotation=45)
        
        # Adjust layout to prevent label cutoff
        _get_plt().setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
        
class StudyValidationThread(QThread):
    """Background thread that validates a REDCap API key by querying for record IDs."""
    validation_complete = Signal(bool, str, str, str)  # success, study_name, api_key, error_msg

    def __init__(self, study_name, api_key):
        super().__init__()
        self.study_name = study_name
        self.api_key = api_key

    def run(self):
        try:
            payload = {
                'token': self.api_key,
                'content': 'record',
                'action': 'export',
                'format': 'json',
                'type': 'flat',
                'fields[0]': 'record_id',
                'rawOrLabel': 'raw',
                'rawOrLabelHeaders': 'raw',
                'exportCheckboxLabel': 'false',
                'exportSurveyFields': 'false',
                'exportDataAccessGroups': 'false',
                'returnFormat': 'json'
            }
            response = requests.post(
                'https://redcap.mountsinai.org/redcap/api/', data=payload
            )
            if response.status_code == 200:
                result = response.json()
                if isinstance(result, dict) and 'error' in result:
                    self.validation_complete.emit(
                        False, self.study_name, self.api_key,
                        f"REDCap error: {result['error']}"
                    )
                elif isinstance(result, list):
                    self.validation_complete.emit(
                        True, self.study_name, self.api_key, ""
                    )
                else:
                    self.validation_complete.emit(
                        False, self.study_name, self.api_key,
                        "Unexpected response format from REDCap."
                    )
            else:
                self.validation_complete.emit(
                    False, self.study_name, self.api_key,
                    f"HTTP {response.status_code}: Unable to connect to database."
                )
        except Exception as e:
            self.validation_complete.emit(False, self.study_name, self.api_key, str(e))


class AddStudyDialog(QDialog):
    """Pop-up dialog for adding a new study API key / database to the application."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add New API Key / Database")
        self.setFixedSize(460, 400)
        self.setWindowFlags(self.windowFlags() | Qt.WindowCloseButtonHint)

        self.validated_name = None
        self.validated_key = None
        self.validated_target = None
        self.validated_start_date = None
        self._validation_thread = None

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(24, 20, 24, 20)

        bold_font = QFont()
        bold_font.setBold(True)
        bold_font.setPointSize(10)

        # Study name row
        name_label = QLabel("Name of study:")
        name_label.setFont(bold_font)
        layout.addWidget(name_label)

        self.study_name_input = QLineEdit()
        self.study_name_input.setPlaceholderText("Enter the name of the study...")
        layout.addWidget(self.study_name_input)

        # API key row
        api_label = QLabel("API key for study:")
        api_label.setFont(bold_font)
        layout.addWidget(api_label)

        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("Enter the REDCap API key...")
        layout.addWidget(self.api_key_input)

        # Target enrollment row
        target_label = QLabel("Target enrollment (optional):")
        target_label.setFont(bold_font)
        layout.addWidget(target_label)

        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText("What is the target enrollment for this study?")
        layout.addWidget(self.target_input)

        # Study start date row
        start_date_label = QLabel("Study start date (optional, YYYY-MM-DD):")
        start_date_label.setFont(bold_font)
        layout.addWidget(start_date_label)

        self.start_date_input = QLineEdit()
        self.start_date_input.setPlaceholderText("e.g. 2025-01-15")
        layout.addWidget(self.start_date_input)

        # Status / error label (hidden until needed)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

        # Buttons
        btn_layout = QHBoxLayout()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        self.enter_btn = QPushButton("Enter")
        self.enter_btn.setDefault(True)
        self.enter_btn.clicked.connect(self._on_enter_clicked)
        btn_layout.addWidget(self.enter_btn)

        layout.addLayout(btn_layout)

    def _on_enter_clicked(self):
        name = self.study_name_input.text().strip()
        api_key = self.api_key_input.text().strip()
        target_text = self.target_input.text().strip()
        start_date_text = self.start_date_input.text().strip()

        if not name:
            self._show_status("Please enter a study name.", error=True)
            return
        if not api_key:
            self._show_status("Please enter an API key.", error=True)
            return

        # Validate target enrollment if provided
        if target_text:
            try:
                int(target_text)
            except ValueError:
                self._show_status("Target enrollment must be a whole number.", error=True)
                return

        # Validate start date if provided
        if start_date_text:
            try:
                date.fromisoformat(start_date_text)
            except ValueError:
                self._show_status("Start date must be in YYYY-MM-DD format.", error=True)
                return

        self.enter_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self._show_status("Validating API key with REDCap...", error=False)

        self._validation_thread = StudyValidationThread(name, api_key)
        self._validation_thread.validation_complete.connect(
            lambda ok, sn, ak, err: self._on_validation_done(ok, sn, ak, err, target_text, start_date_text)
        )
        self._validation_thread.start()

    def _on_validation_done(self, success, study_name, api_key, error_msg, target_text, start_date_text):
        self.enter_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)

        if success:
            self.validated_name = study_name
            self.validated_key = api_key
            self.validated_target = target_text if target_text else None
            self.validated_start_date = start_date_text if start_date_text else None
            self.accept()
        else:
            self._show_status(error_msg, error=True)

    def _show_status(self, message, error=True):
        if error:
            self.status_label.setStyleSheet("color: #c62828; font-weight: bold;")
        else:
            self.status_label.setStyleSheet("color: #555555;")
        self.status_label.setText(message)
        self.status_label.setVisible(True)


class RemoveStudiesDialog(QDialog):
    """Pop-up dialog for removing studies from api_keys.json and the current user's permissions."""

    def __init__(self, studies, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Remove Studies")
        self.setMinimumWidth(400)
        self.setWindowFlags(self.windowFlags() | Qt.WindowCloseButtonHint)

        self.studies_to_remove = []  # filled on accept

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(24, 20, 24, 20)

        bold_font = QFont()
        bold_font.setBold(True)
        bold_font.setPointSize(10)

        header = QLabel("Select studies to remove:")
        header.setFont(bold_font)
        layout.addWidget(header)

        # Scrollable list of checkboxes
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(300)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(4, 4, 4, 4)

        self._checkboxes = {}
        for study_name in studies:
            cb = QCheckBox(study_name)
            self._checkboxes[study_name] = cb
            container_layout.addWidget(cb)

        scroll.setWidget(container)
        layout.addWidget(scroll)

        # Buttons
        btn_layout = QHBoxLayout()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        delete_btn = QPushButton("Delete Studies")
        delete_btn.clicked.connect(self._on_delete_clicked)
        btn_layout.addWidget(delete_btn)

        layout.addLayout(btn_layout)

    def _on_delete_clicked(self):
        self.studies_to_remove = [
            name for name, cb in self._checkboxes.items() if cb.isChecked()
        ]
        self.accept()


class WheelScrollArea(QScrollArea):
    """QScrollArea that always scrolls vertically on mouse wheel,
    even when child widgets (e.g. matplotlib canvases) are under the cursor."""
    def wheelEvent(self, event):
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() - event.angleDelta().y()
        )
        event.accept()


class ClinicalTrialApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Clinical Trial Visualization")
        self.setGeometry(100, 100, 1400, 900)
        
        # Store active threads
        self.active_threads = []
        
        # Current user tracking
        self.current_user = None
        self.user_permissions = None
        
        # Load API keys and user permissions from files
        self.api_keys = self.load_api_keys()
        self.user_data = self.load_user_permissions()

        # Central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Create tab widget
        self.tabs = QTabWidget()
        layout = QVBoxLayout(central_widget)
        layout.addWidget(self.tabs)
        
        self.setup_login_tab()
        self.setup_selection_tab()
        self.setup_visualization_tab()
        
        # Start with login tab
        self.tabs.setCurrentIndex(0)
        self.tabs.setTabEnabled(1, False)  # Disable selection tab initially
        self.tabs.setTabEnabled(2, False)  # Disable visualization tab initially

    def load_api_keys(self):
        """Load API keys from JSON file"""
        try:
            api_keys_path = get_config_path('api_keys.json')
            
            with open(api_keys_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            api_keys_path = get_config_path('api_keys.json')
            config_dir = os.path.dirname(api_keys_path)
            os.makedirs(config_dir, exist_ok=True)
            if sys.platform == 'darwin':
                import subprocess
                subprocess.run(['open', config_dir])
            QMessageBox.critical(None, "Config files missing",
                f"api_keys.json was not found.\n\n"
                f"A Finder window has opened showing the folder where you "
                f"need to place it:\n\n{config_dir}\n\n"
                f"Drag api_keys.json and user_permissions.json into that "
                f"folder, then relaunch the app.")
            return {}
        except json.JSONDecodeError:
            QMessageBox.critical(None, "Error",
                "Invalid JSON format in api_keys.json!\n"
                "Please check the file format.")
            return {}
        except Exception as e:
            QMessageBox.critical(None, "Error", f"Error loading API keys: {str(e)}")
            return {}
    
    def load_user_permissions(self):
        """Load user permissions from JSON file"""
        try:
            permissions_path = get_config_path('user_permissions.json')
            
            with open(permissions_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            permissions_path = get_config_path('user_permissions.json')
            config_dir = os.path.dirname(permissions_path)
            os.makedirs(config_dir, exist_ok=True)
            if sys.platform == 'darwin':
                import subprocess
                subprocess.run(['open', config_dir])
            QMessageBox.critical(None, "Config files missing",
                f"user_permissions.json was not found.\n\n"
                f"A Finder window has opened showing the folder where you "
                f"need to place it:\n\n{config_dir}\n\n"
                f"Drag api_keys.json and user_permissions.json into that "
                f"folder, then relaunch the app.")
            return {"users": {}}
        except json.JSONDecodeError:
            QMessageBox.critical(None, "Error",
                "Invalid JSON format in user_permissions.json!\n"
                "Please check the file format.")
            return {"users": {}}
        except Exception as e:
            QMessageBox.critical(None, "Error", f"Error loading user permissions: {str(e)}")
            return {"users": {}}
        
    def get_studies(self):
        """Get list of studies with their API keys from loaded JSON, filtered by user permissions"""
        studies = []
        
        # If no user is logged in, return empty list
        if not self.current_user:
            return studies
        
        # Get accessible studies for the current user
        user_accessible_studies = self.user_permissions.get('accessible_studies', [])
        
        for study_name, api_key in self.api_keys.items():
            # Only include studies the user has access to
            if study_name in user_accessible_studies:
                studies.append({
                    "name": study_name,
                    "api_key": api_key
                })
        return studies
            
    def close_event(self, event):
        """Clean up threads when closing the application"""
        self.cleanup_threads()
        event.accept()
    
    def cleanup_threads(self):
        """Safely cleanup all active threads"""
        for thread in self.active_threads[:]:  # Use slice copy to avoid modification during iteration
            if thread.isRunning():
                thread.quit()
                thread.wait(1000)  # Wait up to 1 second for thread to finish
            try:
                thread.deleteLater()
            except RuntimeError:
                pass  # Thread already deleted
        self.active_threads.clear()
        
    def setup_login_tab(self):
        self.login_widget = QWidget()
        layout = QVBoxLayout(self.login_widget)
        layout.setAlignment(Qt.AlignCenter)
        
        # Title
        title = QLabel("Clinical Trial Visualization")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # Login form
        form_widget = QWidget()
        form_layout = QVBoxLayout(form_widget)
        form_widget.setFixedWidth(300)
        
        form_layout.addWidget(QLabel("Username:"))
        self.username_entry = QLineEdit()
        form_layout.addWidget(self.username_entry)
        
        form_layout.addWidget(QLabel("Password:"))
        self.password_entry = QLineEdit()
        self.password_entry.setEchoMode(QLineEdit.Password)
        form_layout.addWidget(self.password_entry)
        
        login_btn = QPushButton("Login")
        login_btn.clicked.connect(self.login)
        form_layout.addWidget(login_btn)
        
        # Center the form
        form_container = QHBoxLayout()
        form_container.addStretch()
        form_container.addWidget(form_widget)
        form_container.addStretch()
        
        layout.addLayout(form_container)
        
        self.tabs.addTab(self.login_widget, "Login")
    
    def setup_selection_tab(self):
        self.selection_widget = QWidget()
        self.selection_layout = QVBoxLayout(self.selection_widget)

        # Header row: title + logout button
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Select Studies to Visualize")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        header_layout.addWidget(title)

        header_layout.addStretch()

        sel_logout_btn = QPushButton("Logout")
        sel_logout_btn.clicked.connect(self.logout)
        sel_logout_btn.setFixedWidth(80)
        header_layout.addWidget(sel_logout_btn)

        self.selection_layout.addWidget(header_widget)
        
        # User info label
        self.user_info_label = QLabel("Please log in to view available studies.")
        self.user_info_label.setStyleSheet("QLabel { color: #666; font-style: italic; margin: 10px; }")
        self.selection_layout.addWidget(self.user_info_label)
        
        # Container for study checkboxes
        self.studies_container = QWidget()
        self.studies_layout = QVBoxLayout(self.studies_container)
        self.selection_layout.addWidget(self.studies_container)
        
        # Study checkboxes (will be populated in refresh_studies_list)
        self.study_checkboxes = {}
        
        # Generate button
        self.generate_btn = QPushButton("Generate Visualizations")
        self.generate_btn.clicked.connect(self.generate_visualizations)
        self.generate_btn.setEnabled(False)  # Disabled until studies are loaded
        self.selection_layout.addWidget(self.generate_btn)

        # "Add new study" button — lives directly below Generate Visualizations
        self.add_study_btn = QPushButton("Would you like to add a new API key/Database?")
        self.add_study_btn.clicked.connect(self.open_add_study_dialog)
        self.selection_layout.addWidget(self.add_study_btn)

        # "Remove studies" button — lives directly below Add button
        self.remove_study_btn = QPushButton("Do you want to remove any of these studies from the list?")
        self.remove_study_btn.clicked.connect(self.open_remove_studies_dialog)
        self.selection_layout.addWidget(self.remove_study_btn)

        self.selection_layout.addStretch()
        self.tabs.addTab(self.selection_widget, "Select Studies")
    
    def refresh_studies_list(self):
        """Refresh the studies list based on current user permissions"""
        # Clear all widgets from the studies container (checkboxes + any status labels)
        while self.studies_layout.count():
            item = self.studies_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.study_checkboxes.clear()
        
        # Update user info
        if self.current_user and self.user_permissions:
            role = self.user_permissions.get('role', 'User')
            accessible_count = len(self.user_permissions.get('accessible_studies', []))
            self.user_info_label.setText(
                f"Logged in as: {self.current_user} ({role}) | "
                f"Accessible studies: {accessible_count}"
            )
            
            # Get studies for this user
            studies = self.get_studies()
            
            if studies:
                # Create checkboxes for accessible studies
                for study in studies:
                    checkbox = QCheckBox(study['name'])
                    checkbox.study_data = study
                    self.study_checkboxes[study['name']] = checkbox
                    self.studies_layout.addWidget(checkbox)
                
                self.generate_btn.setEnabled(True)
            else:
                no_access_label = QLabel("No studies accessible for your account.")
                no_access_label.setStyleSheet("QLabel { color: #d32f2f; font-weight: bold; }")
                self.studies_layout.addWidget(no_access_label)
                self.generate_btn.setEnabled(False)
        else:
            self.user_info_label.setText("Please log in to view available studies.")
            self.generate_btn.setEnabled(False)
    
    def setup_visualization_tab(self):
        self.viz_widget = QWidget()
        layout = QVBoxLayout(self.viz_widget)
        
        # Header with title and user info
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        
        # Title
        title = QLabel("Visualizations")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        header_layout.addWidget(title)
        
        header_layout.addStretch()
        
        # User info and logout button
        self.viz_user_label = QLabel("")
        self.viz_user_label.setStyleSheet("QLabel { color: #666; }")
        header_layout.addWidget(self.viz_user_label)
        
        logout_btn = QPushButton("Logout")
        logout_btn.clicked.connect(self.logout)
        logout_btn.setFixedWidth(80)
        header_layout.addWidget(logout_btn)
        
        layout.addWidget(header_widget)
        
        # Scrollable area for charts
        scroll_area = WheelScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        self.chart_widget = ChartWidget()
        scroll_area.setWidget(self.chart_widget)
        
        layout.addWidget(scroll_area)
        
        # Back button
        back_btn = QPushButton("Back to Selection")
        back_btn.clicked.connect(self.go_back_to_selection)
        layout.addWidget(back_btn)
        
        self.tabs.addTab(self.viz_widget, "Visualizations")
    
    # Removed duplicate get_studies method - now using the one defined earlier with permissions filtering
    
    def login(self):
        username = self.username_entry.text().strip()
        password = self.password_entry.text()
        
        if self.validate_login(username, password):
            # Set current user and their permissions
            self.current_user = username
            self.user_permissions = self.user_data['users'].get(username, {})
            
            # Update window title to show logged in user
            user_role = self.user_permissions.get('role', 'User')
            self.setWindowTitle(f"Clinical Trial Visualization - {username} ({user_role})")
            
            # Refresh the studies list and enable next tab
            self.refresh_studies_list()
            
            accessible_studies_count = len(self.user_permissions.get('accessible_studies', []))
            QMessageBox.information(self, "Success", 
                f"Login successful!\n"
                f"User: {username}\n"
                f"Role: {user_role}\n"
                f"Accessible studies: {accessible_studies_count}")
            
            self.tabs.setTabEnabled(1, True)
            self.tabs.setCurrentIndex(1)
        else:
            QMessageBox.critical(self, "Error", "Invalid username or password!")
    
    def validate_login(self, username, password):
        """Validate login using user_permissions.json"""
        users = self.user_data.get('users', {})
        user_info = users.get(username)
        if user_info and user_info.get('password') == password:
            return True
        return False
    
    def reset_visualization_state(self):
        """Reset the visualization tab to prepare for new data"""
        # Clear all charts
        self.chart_widget.clear_charts()
        
        # Cleanup any existing threads
        self.cleanup_threads()
        
        # Reset counters
        self.pending_studies = 0
        self.completed_studies = 0
    
    def generate_visualizations(self):
        selected_studies = []
        for checkbox in self.study_checkboxes.values():
            if checkbox.isChecked():
                selected_studies.append(checkbox.study_data)
        
        if not selected_studies:
            QMessageBox.warning(self, "Warning", "Please select at least one study!")
            return
        
        # Reset visualization state first
        self.reset_visualization_state()
        
        # Update user info in visualization tab
        if self.current_user and self.user_permissions:
            role = self.user_permissions.get('role', 'User')
            self.viz_user_label.setText(f"Logged in as: {self.current_user} ({role})")
        
        # Show loading message
        loading_label = QLabel("Loading data and generating visualizations...")
        loading_label.setAlignment(Qt.AlignCenter)
        self.chart_widget.layout.addWidget(loading_label)
        
        # Switch to visualization tab
        self.tabs.setTabEnabled(2, True)
        self.tabs.setCurrentIndex(2)
        
        # Fetch data for each study
        self.pending_studies = len(selected_studies)
        self.completed_studies = 0
        
        for study in selected_studies:
            fetcher = DataFetcher(study['api_key'], study['name'])
            fetcher.data_fetched.connect(self.on_data_fetched)
            fetcher.error_occurred.connect(self.on_error)
            fetcher.finished.connect(lambda: self.cleanup_finished_threads())
            self.active_threads.append(fetcher)
            fetcher.start()
    
    def cleanup_finished_threads(self):
        """Remove finished threads from active_threads list"""
        for thread in self.active_threads[:]:  # Use slice copy
            try:
                if thread.isFinished():
                    self.active_threads.remove(thread)
                    thread.deleteLater()
            except RuntimeError:
                # Thread was already deleted
                if thread in self.active_threads:
                    self.active_threads.remove(thread)
    
    def on_data_fetched(self, data, study_name):
        self.completed_studies += 1
        
        # Remove loading label if this is the first study
        if self.completed_studies == 1:
            # Clear loading message
            while self.chart_widget.layout.count():
                child = self.chart_widget.layout.takeAt(0)
                if child.widget() and isinstance(child.widget(), QLabel) and "Loading" in child.widget().text():
                    child.widget().deleteLater()
                    break
        
        # Add chart for this study
        self.chart_widget.add_chart(data, study_name)
    
    def on_error(self, error_message):
        QMessageBox.critical(self, "Error", f"Failed to fetch data: {error_message}")
    
    def go_back_to_selection(self):
        # Reset visualization state when going back
        self.reset_visualization_state()
        self.tabs.setCurrentIndex(1)
    
    def logout(self):
        """Logout current user and return to login screen"""
        # Confirm logout
        reply = QMessageBox.question(self, "Logout", 
                                   f"Are you sure you want to logout {self.current_user}?",
                                   QMessageBox.Yes | QMessageBox.No,
                                   QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            # Clear user data
            self.current_user = None
            self.user_permissions = None
            
            # Reset window title
            self.setWindowTitle("Clinical Trial Visualization")
            
            # Clear login fields
            self.username_entry.clear()
            self.password_entry.clear()
            
            # Reset visualization and selection tabs
            self.reset_visualization_state()
            self.refresh_studies_list()
            
            # Disable tabs and return to login
            self.tabs.setTabEnabled(1, False)
            self.tabs.setTabEnabled(2, False)
            self.tabs.setCurrentIndex(0)
            
            QMessageBox.information(self, "Logged Out", "You have been logged out successfully.")

    def open_add_study_dialog(self):
        """Open the dialog for adding a new study / API key."""
        dialog = AddStudyDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.save_new_study(
                dialog.validated_name,
                dialog.validated_key,
                dialog.validated_target,
                dialog.validated_start_date
            )

    def open_remove_studies_dialog(self):
        """Open the dialog for removing studies."""
        # Build the list the current user can see
        accessible = self.user_permissions.get('accessible_studies', []) if self.user_permissions else []
        if not accessible:
            QMessageBox.information(self, "No Studies", "There are no studies to remove.")
            return
        dialog = RemoveStudiesDialog(accessible, self)
        # Always refresh the list when the dialog closes (accept or reject)
        dialog.finished.connect(lambda _: self.refresh_studies_list())
        if dialog.exec() == QDialog.Accepted and dialog.studies_to_remove:
            self.remove_studies(dialog.studies_to_remove)

    def remove_studies(self, studies_to_remove):
        """Remove selected studies from api_keys.json and the current user's permissions."""
        try:
            for name in studies_to_remove:
                # Remove from in-memory api_keys dict
                self.api_keys.pop(name, None)
                # Remove from current user's accessible_studies
                accessible = self.user_permissions.get('accessible_studies', [])
                if name in accessible:
                    accessible.remove(name)

            # Persist api_keys.json
            api_keys_path = get_config_path('api_keys.json')
            with open(api_keys_path, 'w') as f:
                json.dump(self.api_keys, f, indent=2)

            # Persist user_permissions.json
            permissions_path = get_config_path('user_permissions.json')
            with open(permissions_path, 'w') as f:
                json.dump(self.user_data, f, indent=2)

            self.refresh_studies_list()

            removed_list = ", ".join(f"'{n}'" for n in studies_to_remove)
            QMessageBox.information(
                self, "Studies Removed",
                f"The following studies have been removed:\n{removed_list}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Remove Error", f"Failed to remove studies: {str(e)}")

    def save_new_study(self, study_name, api_key, target=None, start_date=None):
        """Persist a newly validated study to api_keys.json, user_permissions.json,
        and study_config.json, then refresh the selection list and notify the user."""
        try:
            # --- api_keys.json ---
            self.api_keys[study_name] = api_key
            api_keys_path = get_config_path('api_keys.json')
            with open(api_keys_path, 'w') as f:
                json.dump(self.api_keys, f, indent=2)

            # --- user_permissions.json ---
            # self.user_permissions is a reference to the current user's dict inside
            # self.user_data, so appending here updates both simultaneously.
            accessible = self.user_permissions.setdefault('accessible_studies', [])
            if study_name not in accessible:
                accessible.append(study_name)
            permissions_path = get_config_path('user_permissions.json')
            with open(permissions_path, 'w') as f:
                json.dump(self.user_data, f, indent=2)

            # --- study_config.json (target enrollment + start date) ---
            study_config_path = get_config_path('study_config.json')
            try:
                with open(study_config_path, 'r') as f:
                    study_config = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                study_config = {}
            study_config[study_name] = {
                'target_subjects': int(target) if target else None,
                'start_date': start_date if start_date else None
            }
            with open(study_config_path, 'w') as f:
                json.dump(study_config, f, indent=2)

            # Update the live chart widget's recruitment_rates so it takes effect immediately
            if hasattr(self, 'chart_widget'):
                self.chart_widget._load_study_config()

            # Refresh the studies list so the new study appears immediately
            self.refresh_studies_list()

            QMessageBox.information(
                self, "Study Added",
                f"'{study_name}' has been successfully added!\n"
                "The study is now visible in your studies list."
            )
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save study: {str(e)}")


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Modern look
    
    window = ClinicalTrialApp()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()