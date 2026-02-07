"""
JobFinder Pro v4.0 - Enterprise Edition
Professional job search application with advanced features

Author: Waleed Abo Hasan
License: MIT
"""
from tkinter import*
import tkinter as tk
import customtkinter as ctk
import webbrowser
import requests
import json
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, asdict
from enum import Enum
import threading
from queue import Queue
import sqlite3
from pathlib import Path

# ============================================================================
# CONFIGURATION & CONSTANTS
# ============================================================================

class Config:
    """Application configuration"""
    # Appearance
    APPEARANCE_MODE = "dark"
    THEME_COLOR = "#10B981"
    ACCENT_BLUE = "#1e40af"
    BG_SIDEBAR = "#111827"
    BG_MAIN = "#0F172A"
    BG_FILTER = "#1E293B"
    TEXT_PRIMARY = "#F8FAFC"
    TEXT_SECONDARY = "#94A3B8"
    
    # API
    API_BASE_URL = "https://jobsearch.api.jobtechdev.se/search"
    API_TIMEOUT = 10
    MAX_RESULTS = 100
    
    # Files & Directories
    APP_DIR = Path.home() / ".jobfinder_pro"
    DB_FILE = APP_DIR / "jobfinder.db"
    LOG_FILE = APP_DIR / "app.log"
    CONFIG_FILE = APP_DIR / "config.json"
    CACHE_DIR = APP_DIR / "cache"
    
    # Limits
    MAX_HISTORY = 50
    CACHE_EXPIRY_HOURS = 24
    MAX_FAVORITES = 100
    
    # UI
    WINDOW_WIDTH = 1400
    WINDOW_HEIGHT = 850
    SIDEBAR_WIDTH = 280
    MIN_WINDOW_WIDTH = 1000
    MIN_WINDOW_HEIGHT = 700


class JobStatus(Enum):
    """Job application status"""
    NEW = "new"
    SAVED = "saved"
    APPLIED = "applied"
    INTERVIEW = "interview"
    REJECTED = "rejected"
    ACCEPTED = "accepted"


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class Job:
    """Job data model"""
    id: str
    title: str
    company: str
    location: str
    url: str
    published_date: str
    deadline: str = ""
    description: str = ""
    salary: str = ""
    employment_type: str = ""
    working_hours: str = ""
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_api(cls, hit: dict) -> 'Job':
        """Create Job from API response"""
        return cls(
            id=hit.get('id', ''),
            title=hit.get('headline', 'Utan titel'),
            company=hit.get('employer', {}).get('name', 'Okänd arbetsgivare'),
            location=hit.get('workplace_address', {}).get('municipality', 'Plats ej angiven'),
            url=hit.get('webpage_url', ''),
            published_date=hit.get('publication_date', ''),
            deadline=hit.get('application_deadline', ''),
            description=hit.get('description', {}).get('text', ''),
            salary=hit.get('salary_description', ''),
            employment_type=hit.get('employment_type', {}).get('label', ''),
            working_hours=hit.get('working_hours_type', {}).get('label', '')
        )


@dataclass
class SearchQuery:
    """Search query data model"""
    query: str
    locations: List[str]
    filters: Dict
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


# ============================================================================
# DATABASE MANAGER
# ============================================================================

class DatabaseManager:
    """Manages SQLite database operations"""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
    
    def _init_database(self):
        """Initialize database tables"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Search history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS search_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    locations TEXT,
                    filters TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Saved jobs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS saved_jobs (
                    job_id TEXT PRIMARY KEY,
                    title TEXT,
                    company TEXT,
                    location TEXT,
                    url TEXT,
                    status TEXT DEFAULT 'saved',
                    notes TEXT,
                    saved_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                    data TEXT
                )
            """)
            
            # Watched searches table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS watched_searches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    query TEXT,
                    locations TEXT,
                    filters TEXT,
                    email TEXT,
                    created_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_check DATETIME,
                    active INTEGER DEFAULT 1
                )
            """)
            
            conn.commit()
    
    def save_search(self, query: SearchQuery):
        """Save search to history"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO search_history (query, locations, filters)
                VALUES (?, ?, ?)
            """, (query.query, json.dumps(query.locations), json.dumps(query.filters)))
            conn.commit()
    
    def get_search_history(self, limit: int = 50) -> List[Dict]:
        """Get search history"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT query, locations, timestamp 
                FROM search_history 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (limit,))
            
            return [
                {
                    'query': row[0],
                    'locations': json.loads(row[1]) if row[1] else [],
                    'timestamp': row[2]
                }
                for row in cursor.fetchall()
            ]
    
    def save_job(self, job: Job, status: JobStatus = JobStatus.SAVED, notes: str = ""):
        """Save job to favorites"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO saved_jobs 
                (job_id, title, company, location, url, status, notes, data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (job.id, job.title, job.company, job.location, job.url, 
                  status.value, notes, json.dumps(job.to_dict())))
            conn.commit()
    
    def get_saved_jobs(self, status: Optional[JobStatus] = None) -> List[Job]:
        """Get saved jobs, optionally filtered by status"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            if status:
                cursor.execute("""
                    SELECT data FROM saved_jobs 
                    WHERE status = ?
                    ORDER BY saved_date DESC
                """, (status.value,))
            else:
                cursor.execute("""
                    SELECT data FROM saved_jobs 
                    ORDER BY saved_date DESC
                """)
            
            return [Job(**json.loads(row[0])) for row in cursor.fetchall()]
    
    def delete_job(self, job_id: str):
        """Delete saved job"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM saved_jobs WHERE job_id = ?", (job_id,))
            conn.commit()


# ============================================================================
# API CLIENT
# ============================================================================

class JobAPIClient:
    """JobTech API client with error handling and caching"""
    
    def __init__(self):
        self.base_url = Config.API_BASE_URL
        self.timeout = Config.API_TIMEOUT
        self.session = requests.Session()
        self.cache_dir = Config.CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
    
    def search(self, query: str, locations: List[str] = None, 
               filters: Dict = None, limit: int = None) -> Dict:
        """
        Search for jobs
        
        Args:
            query: Search query
            locations: List of municipalities
            filters: Filter dictionary
            limit: Max results
            
        Returns:
            Dictionary with 'hits' and 'total'
        """
        params = {
            'q': query,
            'limit': limit or Config.MAX_RESULTS
        }
        
        if locations:
            params['municipality'] = ','.join(locations)
        
        # Apply filters to params
        if filters:
            params.update(self._build_filter_params(filters))
        
        try:
            self.logger.info(f"Searching: {query} in {locations}")
            response = self.session.get(
                self.base_url, 
                params=params, 
                timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            self.logger.info(f"Found {data.get('total', {}).get('value', 0)} results")
            
            return data
            
        except requests.RequestException as e:
            self.logger.error(f"API request failed: {e}")
            raise
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse API response: {e}")
            raise
    
    def _build_filter_params(self, filters: Dict) -> Dict:
        """Convert filters to API parameters"""
        params = {}
        
        # Omfattning
        if filters.get('omfattning') == 'heltid':
            params['working-hours-type'] = 'heltid'
        elif filters.get('omfattning') == 'deltid':
            params['working-hours-type'] = 'deltid'
        
        # Publicerad
        if filters.get('publicerad') != 'alla':
            period = filters['publicerad']
            if period == 'idag':
                params['published-after'] = datetime.now().strftime('%Y-%m-%d')
            elif period == '7dagar':
                date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
                params['published-after'] = date
            elif period == '30dagar':
                date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
                params['published-after'] = date
        
        return params


# ============================================================================
# LOGGER SETUP
# ============================================================================

def setup_logging():
    """Configure application logging"""
    Config.APP_DIR.mkdir(parents=True, exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(Config.LOG_FILE),
            logging.StreamHandler()
        ]
    )
    
    # Reduce requests library verbosity
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# ============================================================================
# UI COMPONENTS
# ============================================================================

class FilterMenu(ctk.CTkScrollableFrame):
    """Professional filter menu - same as v3.0 but with improved structure"""
    
    def __init__(self, parent, on_filter_change_callback: Callable):
        super().__init__(parent, fg_color="white", corner_radius=10)
        self.on_filter_change = on_filter_change_callback
        self.logger = logging.getLogger(__name__)
        
        # Filter values
        self.filter_values = {
            'omfattning': tk.StringVar(value='alla'),
            'anstallningsform': {
                'tillsvidare': tk.BooleanVar(value=False),
                'behov': tk.BooleanVar(value=False),
                'sommar': tk.BooleanVar(value=False)
            },
            'arbetsplats': {
                'distans': tk.BooleanVar(value=False),
                'oppen': tk.BooleanVar(value=False)
            },
            'publicerad': tk.StringVar(value='alla'),
            'kvalifikationer': {
                'nystart': tk.BooleanVar(value=False),
                'utan_korkort': tk.BooleanVar(value=False)
            },
            'utbildning': tk.StringVar(value='alla')
        }
        
        self.setup_ui()
    
    def setup_ui(self):
        """Build filter menu UI - same as v3.0"""
        # Header
        header_frame = ctk.CTkFrame(self, fg_color=Config.ACCENT_BLUE, corner_radius=8)
        header_frame.pack(fill="x", padx=10, pady=(10, 5))
        
        btn_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=8)
        
        ctk.CTkLabel(btn_frame, text="🔽 Filter", text_color="white", 
                    font=("Inter", 14, "bold")).pack(side="left", padx=5)
        
        ctk.CTkButton(btn_frame, text="🔔 Bevaka", fg_color="#3b82f6", 
                     hover_color="#2563eb", width=80, height=25, 
                     font=("Inter", 10), command=self.bevaka).pack(side="left", padx=5)
        
        ctk.CTkButton(btn_frame, text="✕ Rensa", fg_color="#dc2626", 
                     hover_color="#b91c1c", width=80, height=25,
                     font=("Inter", 10, "bold"), command=self.clear_filters).pack(side="right", padx=5)
        
        # === OMFATTNING ===
        self.create_section_header("Omfattning")
        omfattning_frame = self.create_section_frame()
        
        for value, label in [('alla', 'Alla'), ('heltid', 'Heltid'), ('deltid', 'Deltid')]:
            ctk.CTkRadioButton(
                omfattning_frame, text=label, 
                variable=self.filter_values['omfattning'],
                value=value, fg_color=Config.THEME_COLOR, text_color="#1f2937",
                command=self.notify_change
            ).pack(anchor="w", pady=3, padx=20)
        
        # === PUBLICERAD ===
        self.create_section_header("Publicerad")
        pub_frame = self.create_section_frame()
        
        for value, label in [('alla', 'Alla'), ('idag', 'Idag'), 
                            ('7dagar', 'Senaste 7 dagarna'), 
                            ('30dagar', 'Senaste 30 dagarna')]:
            ctk.CTkRadioButton(
                pub_frame, text=label,
                variable=self.filter_values['publicerad'],
                value=value, fg_color=Config.THEME_COLOR, text_color="#1f2937",
                command=self.notify_change
            ).pack(anchor="w", pady=3, padx=20)
        
        # Distance and salary (simplified for brevity)
        self.distance_var = tk.IntVar(value=50)
        self.salary_var = tk.IntVar(value=0)
        self.sort_var = tk.StringVar(value='relevans')
    
    def create_section_header(self, text: str):
        """Create section header"""
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="x", padx=10, pady=(15, 5))
        ctk.CTkLabel(frame, text=text, text_color=Config.ACCENT_BLUE,
                    font=("Inter", 13, "bold"), anchor="w").pack(side="left", padx=5)
    
    def create_section_frame(self):
        """Create section frame"""
        frame = ctk.CTkFrame(self, fg_color="#f9fafb", corner_radius=6)
        frame.pack(fill="x", padx=10, pady=5)
        return frame
    
    def notify_change(self):
        """Notify filter change"""
        if self.on_filter_change:
            self.on_filter_change(self.get_active_filters())
    
    def get_active_filters(self) -> Dict:
        """Get active filters"""
        return {
            'omfattning': self.filter_values['omfattning'].get(),
            'publicerad': self.filter_values['publicerad'].get(),
            'distance': self.distance_var.get(),
            'salary': self.salary_var.get(),
            'sort': self.sort_var.get()
        }
    
    def clear_filters(self):
        """Clear all filters"""
        self.filter_values['omfattning'].set('alla')
        self.filter_values['publicerad'].set('alla')
        self.distance_var.set(50)
        self.salary_var.set(0)
        self.sort_var.set('relevans')
        self.notify_change()
        self.logger.info("Filters cleared")
    
    def bevaka(self):
        """Watch search - placeholder"""
        self.logger.info("Watch feature activated")


class SavedJobsPanel(ctk.CTkToplevel):
    """Panel for managing saved jobs"""
    
    def __init__(self, parent, db_manager: DatabaseManager):
        super().__init__(parent)
        self.db = db_manager
        self.title("Sparade Jobb")
        self.geometry("900x600")
        self.attributes("-topmost", True)
        
        self.setup_ui()
        self.load_jobs()
    
    def setup_ui(self):
        """Setup UI"""
        # Header
        header = ctk.CTkFrame(self, fg_color=Config.ACCENT_BLUE, height=60)
        header.pack(fill="x")
        
        ctk.CTkLabel(header, text="💾 Sparade Jobb", 
                    font=("Inter", 20, "bold"), text_color="white").pack(pady=15)
        
        # Filter by status
        status_frame = ctk.CTkFrame(self, fg_color="transparent")
        status_frame.pack(fill="x", padx=20, pady=10)
        
        ctk.CTkLabel(status_frame, text="Filtrera:", 
                    font=("Inter", 12, "bold")).pack(side="left", padx=5)
        
        self.status_var = tk.StringVar(value="all")
        for value, label in [('all', 'Alla'), ('saved', 'Sparade'), 
                            ('applied', 'Sökt'), ('interview', 'Intervju')]:
            ctk.CTkRadioButton(
                status_frame, text=label, variable=self.status_var,
                value=value, command=self.load_jobs
            ).pack(side="left", padx=5)
        
        # Jobs list
        self.jobs_frame = ctk.CTkScrollableFrame(self)
        self.jobs_frame.pack(fill="both", expand=True, padx=20, pady=10)
    
    def load_jobs(self):
        """Load and display saved jobs"""
        for widget in self.jobs_frame.winfo_children():
            widget.destroy()
        
        status_filter = None if self.status_var.get() == 'all' else JobStatus(self.status_var.get())
        jobs = self.db.get_saved_jobs(status_filter)
        
        if not jobs:
            ctk.CTkLabel(self.jobs_frame, text="Inga sparade jobb",
                        font=("Inter", 14), text_color="gray").pack(pady=50)
            return
        
        for job in jobs:
            self.create_job_card(job)
    
    def create_job_card(self, job: Job):
        """Create job card"""
        card = ctk.CTkFrame(self.jobs_frame, fg_color="#f3f4f6", corner_radius=8)
        card.pack(fill="x", pady=5, padx=5)
        
        # Title
        title_btn = ctk.CTkButton(
            card, text=job.title, fg_color="transparent", 
            hover_color="#e5e7eb", anchor="w",
            font=("Inter", 13, "bold"), text_color="#1f2937",
            command=lambda: webbrowser.open(job.url)
        )
        title_btn.pack(fill="x", padx=10, pady=(10, 5))
        
        # Company & location
        info = ctk.CTkLabel(card, text=f"🏢 {job.company} • 📍 {job.location}",
                           font=("Inter", 10), text_color="#6b7280", anchor="w")
        info.pack(fill="x", padx=10, pady=(0, 5))
        
        # Action buttons
        btn_frame = ctk.CTkFrame(card, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=(5, 10))
        
        ctk.CTkButton(
            btn_frame, text="🗑️ Ta bort", width=80, height=25,
            fg_color="#dc2626", hover_color="#b91c1c",
            command=lambda: self.delete_job(job.id)
        ).pack(side="right", padx=2)
        
        ctk.CTkButton(
            btn_frame, text="🔗 Öppna", width=80, height=25,
            fg_color=Config.THEME_COLOR, hover_color="#059669",
            command=lambda: webbrowser.open(job.url)
        ).pack(side="right", padx=2)
    
    def delete_job(self, job_id: str):
        """Delete job"""
        self.db.delete_job(job_id)
        self.load_jobs()


# ============================================================================
# MAIN APPLICATION
# ============================================================================

class JobFinderPro(ctk.CTk):
    """Main application class"""
    
    def __init__(self):
        super().__init__()
        
        # Setup
        setup_logging()
        self.logger = logging.getLogger(__name__)
        self.logger.info("Starting JobFinder Pro v4.0")
        
        # Initialize components
        self.db = DatabaseManager(Config.DB_FILE)
        self.api = JobAPIClient()
        
        # State
        self.selected_orts = []
        self.current_filters = {}
        self.all_jobs = []
        self.filter_visible = False
        
        # Setup window
        self.title("JobFinder Pro v4.0 - Enterprise Edition          By Waleed Abo Hasan")
        self.geometry(f"{Config.WINDOW_WIDTH}x{Config.WINDOW_HEIGHT}")
        self.minsize(Config.MIN_WINDOW_WIDTH, Config.MIN_WINDOW_HEIGHT)
        self.configure(fg_color=Config.BG_MAIN)
        
        ctk.set_appearance_mode(Config.APPEARANCE_MODE)
        
        

        # Build UI
        self.setup_ui()
        self.load_history()
        
        self.logger.info("Application initialized successfully")
    
    def setup_ui(self):
        """Setup main UI"""
        # Grid configuration
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # Sidebar
        self.setup_sidebar()
        
        # Main content
        self.setup_main_content()
    
    def setup_sidebar(self):
        """Setup sidebar with history and saved jobs"""
        sidebar = ctk.CTkFrame(self, width=Config.SIDEBAR_WIDTH, 
                              fg_color=Config.BG_SIDEBAR, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        
        # Logo/Title
        ctk.CTkLabel(sidebar, text="JobFinder Pro", 
                    font=("Inter", 20, "bold"), 
                    text_color=Config.THEME_COLOR).pack(pady=20)
        
        # Saved jobs button
        ctk.CTkButton(
            sidebar, text="💾 Sparade Jobb", 
            fg_color=Config.THEME_COLOR, hover_color="#059669",
            height=40, font=("Inter", 12, "bold"),
            command=self.open_saved_jobs
        ).pack(fill="x", padx=15, pady=(0, 10))
        
        # Statistics button
        ctk.CTkButton(
            sidebar, text="📊 Statistik", 
            fg_color="#3b82f6", hover_color="#2563eb",
            height=40, font=("Inter", 12, "bold"),
            command=self.show_statistics
        ).pack(fill="x", padx=15, pady=(0, 20))
        
        # History
        ctk.CTkLabel(sidebar, text="📜 Tidigare Sökningar",
                    font=("Inter", 14, "bold"), 
                    text_color=Config.THEME_COLOR).pack(pady=(0, 10))
        
        self.history_frame = ctk.CTkScrollableFrame(sidebar, fg_color="transparent")
        self.history_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
    
    def setup_main_content(self):
        """Setup main content area"""
        main_area = ctk.CTkFrame(self, fg_color="transparent")
        main_area.grid(row=0, column=1, sticky="nsew")
        main_area.grid_columnconfigure(0, weight=1)
        main_area.grid_rowconfigure(1, weight=1)
        
        # Search bar
        self.setup_search_bar(main_area)
        
        # Content with filters
        content_area = ctk.CTkFrame(main_area, fg_color="transparent")
        content_area.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        content_area.grid_columnconfigure(1, weight=1)
        content_area.grid_rowconfigure(0, weight=1)
        
        # Filter panel
        self.filter_panel = FilterMenu(content_area, self.apply_filters)
        
        # Results area
        self.setup_results_area(content_area)
    
    def setup_search_bar(self, parent):
        """Setup search bar"""
        search_bar = ctk.CTkFrame(parent, fg_color="transparent")
        search_bar.grid(row=0, column=0, sticky="ew", padx=20, pady=15)
        
        # Location button
        self.btn_ort = ctk.CTkButton(
            search_bar, text="📍 Välj Ort",
            fg_color="#1E293B", hover_color="#334155",
            width=150, height=45, corner_radius=10,
            font=("Inter", 12, "bold"),
            command=self.open_ort_picker
        )
        self.btn_ort.pack(side="left", padx=5)
        
        # Search entry
        self.entry_yrke = ctk.CTkEntry(
            search_bar, placeholder_text="🔍 Vad vill du jobba som?",
            height=45, fg_color="#1E293B", border_color="#334155",
            corner_radius=10, font=("Inter", 12)
        )
        self.entry_yrke.pack(side="left", fill="x", expand=True, padx=5)
        self.entry_yrke.bind("<Return>", lambda e: self.start_search())
        
        # Filter toggle
        self.btn_filter = ctk.CTkButton(
            search_bar, text="🔧 Filter",
            fg_color="#3b82f6", hover_color="#2563eb",
            width=100, height=45, corner_radius=10,
            font=("Inter", 12, "bold"),
            command=self.toggle_filter
        )
        self.btn_filter.pack(side="left", padx=5)
        
        # Search button
        self.btn_sok = ctk.CTkButton(
            search_bar, text="🔍 Sök Jobb",
            fg_color=Config.THEME_COLOR, hover_color="#059669",
            width=120, height=45, corner_radius=10,
            font=("Inter", 13, "bold"),
            command=self.start_search
        )
        self.btn_sok.pack(side="left", padx=5)
    
    def setup_results_area(self, parent):
        """Setup results display area"""
        results_container = ctk.CTkFrame(parent, fg_color="transparent")
        results_container.grid(row=0, column=1, sticky="nsew")
        results_container.grid_rowconfigure(1, weight=1)
        results_container.grid_columnconfigure(0, weight=1)
        
        # Stats bar
        self.stats_frame = ctk.CTkFrame(
            results_container, fg_color=Config.BG_FILTER,
            height=40, corner_radius=8
        )
        self.stats_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        
        self.stats_label = ctk.CTkLabel(
            self.stats_frame, text="🎯 Sök efter jobb ovan",
            font=("Inter", 12, "bold"), text_color=Config.TEXT_SECONDARY
        )
        self.stats_label.pack(pady=10)
        
        # Results text
        self.results_area = tk.Text(
            results_container, wrap="word", bg=Config.BG_MAIN,
            fg=Config.TEXT_PRIMARY, font=("Segoe UI", 11),
            padx=20, pady=20, borderwidth=0,
            highlightthickness=0, cursor="arrow"
        )
        self.results_area.grid(row=1, column=0, sticky="nsew")
        
        # Scrollbar
        scrollbar = ctk.CTkScrollbar(results_container, command=self.results_area.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.results_area.configure(yscrollcommand=scrollbar.set)
    
    def toggle_filter(self):
        """Toggle filter panel visibility"""
        if self.filter_visible:
            self.filter_panel.grid_forget()
            self.btn_filter.configure(text="🔧 Filter")
            self.filter_visible = False
        else:
            self.filter_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 15))
            self.btn_filter.configure(text="✕ Dölj Filter")
            self.filter_visible = True
    
    def apply_filters(self, filters: Dict):
        """Apply filters to current results"""
        self.current_filters = filters
        if self.all_jobs:
            filtered = self.filter_jobs(self.all_jobs, filters)
            self.display_jobs(filtered)
    
    def filter_jobs(self, jobs: List[Job], filters: Dict) -> List[Job]:
        """Filter jobs based on criteria"""
        filtered = jobs
        
        # Apply filters...
        # (Implementation same as v3.0)
        
        return filtered
    
    def start_search(self):
        """Start job search in background thread"""
        query = self.entry_yrke.get().strip()
        if not query:
            self.logger.warning("Empty search query")
            return
        
        # Show loading
        self.results_area.delete(1.0, tk.END)
        self.results_area.insert(tk.END, "🔍 Söker...\n")
        self.stats_label.configure(text="⏳ Söker...")
        self.btn_sok.configure(state="disabled", text="⏳ Söker...")
        
        # Search in background
        search_thread = threading.Thread(
            target=self._search_worker,
            args=(query, self.selected_orts, self.current_filters),
            daemon=True
        )
        search_thread.start()
    
    def _search_worker(self, query: str, locations: List[str], filters: Dict):
        """Background worker for search"""
        try:
            # Save to history
            search_query = SearchQuery(query, locations, filters)
            self.db.save_search(search_query)
            
            # API call
            result = self.api.search(query, locations, filters)
            hits = result.get('hits', [])
            total = result.get('total', {}).get('value', 0)
            
            # Convert to Job objects
            jobs = [Job.from_api(hit) for hit in hits]
            self.all_jobs = jobs
            
            # Update UI in main thread
            self.after(0, lambda: self._display_results(jobs, total))
            
        except Exception as e:
            self.logger.error(f"Search failed: {e}", exc_info=True)
            self.after(0, lambda: self._display_error(str(e)))
        finally:
            self.after(0, lambda: self.btn_sok.configure(
                state="normal", text="🔍 Sök Jobb"
            ))
    
    def _display_results(self, jobs: List[Job], total: int):
        """Display search results"""
        self.results_area.delete(1.0, tk.END)
        
        count = len(jobs)
        self.stats_label.configure(
            text=f"🎯 Visar {count} av {total} jobb" if total > count 
                 else f"🎯 {count} jobb hittades"
        )
        
        if count == 0:
            self.results_area.insert(tk.END, "❌ Inga jobb hittades\n", "noresults")
            return
        
        for i, job in enumerate(jobs, 1):
            self.add_job_card(i, job)
        
        self.load_history()  # Refresh history
    
    def _display_error(self, error: str):
        """Display error message"""
        self.results_area.delete(1.0, tk.END)
        self.results_area.insert(tk.END, f"❌ Fel: {error}\n", "error")
        self.stats_label.configure(text="❌ Sökning misslyckades")
    
    def add_job_card(self, index: int, job: Job):
        """Add job card to results"""
        # Separator
        self.results_area.insert(tk.END, f"\n{'─' * 80}\n", "separator")
        
        # Index
        self.results_area.insert(tk.END, f"#{index}  ", "index")
        
        # Title (clickable)
        tag_name = f"link_{job.id}"
        self.results_area.insert(tk.END, f"{job.title}\n", ("link", tag_name))
        
        # Company & location
        self.results_area.insert(tk.END, f"🏢 {job.company}", "company")
        self.results_area.insert(tk.END, "  •  ", "separator_small")
        self.results_area.insert(tk.END, f"📍 {job.location}\n", "location")
        
        # Save button (text-based)
        save_tag = f"save_{job.id}"
        self.results_area.insert(tk.END, "💾 Spara  ", (save_tag, "save_btn"))
        
        # Configure tags
        self.results_area.tag_config("link", foreground=Config.THEME_COLOR, 
                                    font=("Segoe UI", 13, "bold"), underline=True)
        self.results_area.tag_config("company", foreground="#3b82f6", 
                                    font=("Segoe UI", 11))
        self.results_area.tag_config("location", foreground="#8b5cf6", 
                                    font=("Segoe UI", 11))
        self.results_area.tag_config("save_btn", foreground=Config.THEME_COLOR,
                                    font=("Segoe UI", 10, "bold"), underline=True)
        
        # Bind events
        self.results_area.tag_bind(tag_name, "<Button-1>", 
                                  lambda e: webbrowser.open(job.url))
        self.results_area.tag_bind(save_tag, "<Button-1>",
                                  lambda e: self.save_job(job))
        
        for tag in [tag_name, save_tag]:
            self.results_area.tag_bind(tag, "<Enter>",
                                      lambda e: self.results_area.config(cursor="hand2"))
            self.results_area.tag_bind(tag, "<Leave>",
                                      lambda e: self.results_area.config(cursor="arrow"))
    
    def save_job(self, job: Job):
        """Save job to favorites"""
        try:
            self.db.save_job(job)
            self.logger.info(f"Saved job: {job.title}")
            
            # Show confirmation
            confirm = ctk.CTkToplevel(self)
            confirm.title("Sparat")
            confirm.geometry("300x100")
            confirm.attributes("-topmost", True)
            
            ctk.CTkLabel(confirm, text="✅ Jobb sparat!", 
                        font=("Inter", 14, "bold"),
                        text_color=Config.THEME_COLOR).pack(pady=30)
            
            self.after(1500, confirm.destroy)
            
        except Exception as e:
            self.logger.error(f"Failed to save job: {e}")
    
    def load_history(self):
        """Load and display search history"""
        for widget in self.history_frame.winfo_children():
            widget.destroy()
        
        history = self.db.get_search_history(limit=15)
        
        if not history:
            ctk.CTkLabel(self.history_frame, text="Ingen historik",
                        text_color=Config.TEXT_SECONDARY,
                        font=("Inter", 10, "italic")).pack(pady=10)
            return
        
        for item in history:
            btn = ctk.CTkButton(
                self.history_frame, text=f"🔍 {item['query']}",
                fg_color="transparent", anchor="w",
                text_color=Config.TEXT_SECONDARY, hover_color="#1E293B",
                font=("Inter", 10),
                command=lambda q=item['query']: self.quick_search(q)
            )
            btn.pack(fill="x", pady=2)
    
    def quick_search(self, query: str):
        """Quick search from history"""
        self.entry_yrke.delete(0, tk.END)
        self.entry_yrke.insert(0, query)
        self.start_search()
    
    def open_ort_picker(self):
        """Open location picker - placeholder"""
        self.logger.info("Opening location picker")
        # Use OrtPicker from v3.0
    
    def open_saved_jobs(self):
        """Open saved jobs panel"""
        SavedJobsPanel(self, self.db)
    
    def show_statistics(self):
        """Show search statistics"""
        self.logger.info("Showing statistics")
        # Implement statistics view
    
    def display_jobs(self, jobs: List[Job]):
        """Display filtered jobs"""
        self._display_results(jobs, len(self.all_jobs))


# ============================================================================
# ENTRY POINT
# ============================================================================

def main():
    """Application entry point"""
    try:
        app = JobFinderPro()
        app.mainloop()
    except Exception as e:
        logging.error(f"Application crashed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
