# pages/analysis_page.py

"""
Gelişmiş Portföy Analiz Sayfası - Dinamik Grafik Boyutlandırma

Özellikler:
- Dinamik grafik boyutlandırma (pencere boyutuna göre otomatik uyum)
- Responsive layout
- Resize event handling
- Aspect ratio korunması
"""

from __future__ import annotations

import matplotlib
matplotlib.use('TkAgg')

import customtkinter as ctk
from typing import TYPE_CHECKING, Optional, List, Dict, Any, Callable, Tuple
from dataclasses import dataclass
from enum import Enum
import threading
from datetime import datetime, timedelta
import weakref
import pandas as pd
import time

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

if TYPE_CHECKING:
    from database import Database
    from api_service import APIService

# Config
try:
    from config import COLORS
except ImportError:
    COLORS = {
        "primary": "#1f538d",
        "success": "#2d8659",
        "danger": "#dc3545",
        "warning": "#ffc107",
        "purple": "#6f42c1",
        "cyan": "#17a2b8",
    }


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def is_dataframe_valid(df) -> bool:
    """DataFrame'in geçerli olup olmadığını kontrol et"""
    return df is not None and isinstance(df, pd.DataFrame) and not df.empty


def safe_float(value: Any, default: float = 0.0) -> float:
    """Güvenli float dönüşümü"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ============================================================================
# ENUMS & CONSTANTS
# ============================================================================

class TabName(Enum):
    """Sekme isimleri"""
    GENERAL = "📊 Genel"
    PERFORMANCE = "📈 Performans"
    RISK = "⚠️ Risk"
    COMPARISON = "🔍 Karşılaştırma"
    DIVIDEND = "💰 Temettü"


class Period(Enum):
    """Dönem seçenekleri"""
    DAYS_30 = ("30 Gün", 30)
    DAYS_90 = ("90 Gün", 90)
    MONTHS_6 = ("6 Ay", 180)
    YEAR_1 = ("1 Yıl", 365)
    ALL = ("Tümü", -1)
    
    def __init__(self, label: str, days: int):
        self.label = label
        self.days = days
    
    @classmethod
    def from_label(cls, label: str) -> 'Period':
        for period in cls:
            if period.label == label:
                return period
        return cls.DAYS_90


# ============================================================================
# LAZY IMPORTS
# ============================================================================

def _import_metrics():
    """PortfolioMetrics lazy import"""
    try:
        from utils.metrics import PortfolioMetrics
        return PortfolioMetrics
    except ImportError as e:
        print(f"⚠️ PortfolioMetrics import hatası: {e}")
        return _DummyPortfolioMetrics


def _import_charts():
    """Chart modülleri lazy import"""
    charts = {}
    try:
        from charts.pie_chart import PieChart
        from charts.line_chart import LineChart
        from charts.bar_chart import BarChart
        from charts.heatmap import HeatmapChart
        from charts.treemap import TreemapChart
        charts = {
            'pie': PieChart,
            'line': LineChart,
            'bar': BarChart,
            'heatmap': HeatmapChart,
            'treemap': TreemapChart
        }
    except ImportError as e:
        print(f"⚠️ Chart modülleri yüklenemedi: {e}")
    return charts


class _DummyPortfolioMetrics:
    """Fallback metrics sınıfı"""
    def __init__(self, portfolio, transactions=None, api=None):
        self.portfolio = portfolio or []
        
    def calculate_total_return(self) -> float: return 0.0
    def calculate_volatility(self, days=30) -> float: return 15.0
    def calculate_max_drawdown(self) -> float: return 5.0
    def calculate_sharpe_ratio(self) -> float: return 0.5
    def calculate_diversification_score(self) -> float: return 50.0
    def calculate_period_return(self, days) -> float: return 0.0
    def get_portfolio_composition(self) -> list: return []


# ============================================================================
# KPI DATA CLASS
# ============================================================================

@dataclass
class KPIData:
    """KPI kartı verisi"""
    icon: str
    title: str
    value: str
    subtitle: str
    color: str


# ============================================================================
# RESPONSIVE CHART CONTAINER
# ============================================================================

# pages/analysis_page.py - ResponsiveChartFrame sınıfını güncelle (satır 180-210 civarı)

class ResponsiveChartFrame(ctk.CTkFrame):
    """Dinamik boyutlanan grafik container'ı"""
    
    def __init__(
        self, 
        parent: ctk.CTkFrame,
        theme: str = "dark",
        min_height: int = 200,
        aspect_ratio: float = 2.0,
        **kwargs
    ):
        # fg_color'ı kwargs'dan al veya varsayılan kullan
        fg_color = kwargs.pop('fg_color', ("gray90", "gray13"))
        corner_radius = kwargs.pop('corner_radius', 8)
        
        super().__init__(parent, fg_color=fg_color, corner_radius=corner_radius, **kwargs)
        
        self.theme = theme
        self.min_height = min_height
        self.aspect_ratio = aspect_ratio
        self._figure: Optional[plt.Figure] = None
        self._canvas_widget: Optional[FigureCanvasTkAgg] = None
        self._resize_job = None
        self._last_size = (0, 0)
        
        # Minimum yükseklik ayarla
        self.configure(height=min_height)
        
        # Bind işlemini after ile ertele ve güvenli yap
        self.after(100, self._setup_bindings)
    
    def _setup_bindings(self):
        """Binding'leri güvenli şekilde kur"""
        try:
            # CustomTkinter frame'ler için window seviyesinde bind yap
            toplevel = self.winfo_toplevel()
            if toplevel:
                # Unique tag ile bind et
                self._bind_tag = f"resize_{id(self)}"
                toplevel.bind(f"<Configure>", self._on_toplevel_resize, add="+")
        except Exception as e:
            print(f"Binding hatası (göz ardı edilebilir): {e}")
    
    def _on_toplevel_resize(self, event):
        """Toplevel window resize olayı"""
        try:
            # Sadece bu frame görünüyorsa işlem yap
            if self.winfo_exists() and self.winfo_viewable():
                self._check_resize()
        except:
            pass
    
    def _check_resize(self):
        """Frame boyutunu kontrol et"""
        try:
            new_size = (self.winfo_width(), self.winfo_height())
            
            # Boyut değişmediyse veya çok küçükse işlem yapma
            if new_size == self._last_size or new_size[0] < 50 or new_size[1] < 50:
                return
            
            self._last_size = new_size
            
            # Debounce
            if self._resize_job:
                self.after_cancel(self._resize_job)
            
            self._resize_job = self.after(150, lambda: self._do_resize(new_size[0], new_size[1]))
        except:
            pass
    
    def _do_resize(self, width: int, height: int):
        """Grafik boyutunu güncelle"""
        if self._figure and self._canvas_widget:
            try:
                # DPI'ı al
                dpi = self._figure.get_dpi()
                
                # Padding için margin çıkar
                padding = 16
                new_width = max((width - padding) / dpi, 2)
                new_height = max((height - padding) / dpi, 1.5)
                
                # Figure boyutunu güncelle
                self._figure.set_size_inches(new_width, new_height, forward=True)
                self._figure.tight_layout(pad=0.5)
                
                # Canvas'ı yeniden çiz
                self._canvas_widget.draw_idle()
                
            except Exception as e:
                print(f"Resize hatası: {e}")
    
    def set_figure(self, fig: plt.Figure, canvas: FigureCanvasTkAgg):
        """Figure ve canvas referanslarını kaydet"""
        self._figure = fig
        self._canvas_widget = canvas
    
    def clear(self):
        """İçeriği temizle"""
        # Binding'i temizle
        try:
            toplevel = self.winfo_toplevel()
            if toplevel and hasattr(self, '_bind_tag'):
                toplevel.unbind(f"<Configure>")
        except:
            pass
        
        if self._figure:
            plt.close(self._figure)
            self._figure = None
        
        if self._canvas_widget:
            try:
                self._canvas_widget.get_tk_widget().destroy()
            except:
                pass
            self._canvas_widget = None
        
        for widget in self.winfo_children():
            widget.destroy()


# ============================================================================
# DYNAMIC CHART MANAGER
# ============================================================================

class DynamicChartManager:
    """Dinamik grafik yöneticisi - Responsive tasarım için optimize edilmiş"""
    
    def __init__(self, theme: str = "dark"):
        self.theme = theme
        self._charts: List[Tuple[weakref.ref, weakref.ref, weakref.ref]] = []  # (frame_ref, fig_ref, canvas_ref)
        self._base_dpi = 100
    
    def create_responsive_frame(
        self, 
        parent: ctk.CTkFrame,
        min_height: int = 200,
        aspect_ratio: float = 2.0,
        **kwargs
    ) -> ResponsiveChartFrame:
        """Responsive chart frame oluştur"""
        frame = ResponsiveChartFrame(
            parent,
            theme=self.theme,
            min_height=min_height,
            aspect_ratio=aspect_ratio,
            **kwargs
        )
        return frame
    
    def create_dynamic_figure(
        self, 
        container: ResponsiveChartFrame,
        initial_figsize: Tuple[float, float] = (8, 4)
    ) -> Tuple[plt.Figure, plt.Axes]:
        """Container boyutuna göre dinamik figure oluştur"""
        
        # Container'ın mevcut boyutunu al
        container.update_idletasks()
        width = container.winfo_width()
        height = container.winfo_height()
        
        # Minimum boyutları kontrol et
        if width < 100:
            width = 400
        if height < 100:
            height = 250
        
        # Padding çıkar
        padding = 16
        fig_width = (width - padding) / self._base_dpi
        fig_height = (height - padding) / self._base_dpi
        
        # Minimum figure boyutları
        fig_width = max(fig_width, 3)
        fig_height = max(fig_height, 2)
        
        # Figure oluştur
        fig = plt.Figure(figsize=(fig_width, fig_height), dpi=self._base_dpi)
        fig.set_facecolor('none')
        
        # Tema ayarları
        if self.theme == "dark":
            fig.patch.set_facecolor('#2b2b2b')
        else:
            fig.patch.set_facecolor('#f0f0f0')
        
        ax = fig.add_subplot(111)
        self._style_axes(ax)
        
        return fig, ax
    
    def embed_figure(
        self, 
        fig: plt.Figure, 
        container: ResponsiveChartFrame
    ) -> FigureCanvasTkAgg:
        """Figure'ı container'a yerleştir ve dinamik boyutlandırmayı aktif et"""
        
        canvas = FigureCanvasTkAgg(fig, container)
        canvas.draw()
        
        widget = canvas.get_tk_widget()
        widget.pack(fill="both", expand=True, padx=4, pady=4)
        
        # Container'a referansları kaydet
        container.set_figure(fig, canvas)
        
        # Tracking listesine ekle
        self._charts.append((
            weakref.ref(container),
            weakref.ref(fig),
            weakref.ref(canvas)
        ))
        
        return canvas
    
    def _style_axes(self, ax: plt.Axes):
        """Axes stilini tema'ya göre ayarla"""
        if self.theme == "dark":
            ax.set_facecolor('#2b2b2b')
            ax.tick_params(colors='white', labelsize=9)
            ax.xaxis.label.set_color('white')
            ax.yaxis.label.set_color('white')
            ax.title.set_color('white')
            for spine in ax.spines.values():
                spine.set_color('#555555')
        else:
            ax.set_facecolor('#f8f8f8')
            ax.tick_params(colors='black', labelsize=9)
    
    def cleanup(self):
        """Tüm grafikleri temizle"""
        for frame_ref, fig_ref, canvas_ref in self._charts:
            fig = fig_ref()
            if fig is not None:
                try:
                    plt.close(fig)
                except:
                    pass
            
            canvas = canvas_ref()
            if canvas is not None:
                try:
                    canvas.get_tk_widget().destroy()
                except:
                    pass
            
            frame = frame_ref()
            if frame is not None:
                try:
                    frame.clear()
                except:
                    pass
        
        self._charts.clear()
    
    def refresh_all(self):
        """Tüm grafikleri yeniden boyutlandır"""
        for frame_ref, fig_ref, canvas_ref in self._charts:
            frame = frame_ref()
            fig = fig_ref()
            canvas = canvas_ref()
            
            if frame and fig and canvas:
                try:
                    width = frame.winfo_width()
                    height = frame.winfo_height()
                    
                    if width > 50 and height > 50:
                        fig_width = (width - 16) / self._base_dpi
                        fig_height = (height - 16) / self._base_dpi
                        
                        fig.set_size_inches(max(fig_width, 3), max(fig_height, 2))
                        fig.tight_layout(pad=0.5)
                        canvas.draw_idle()
                except Exception as e:
                    print(f"Refresh hatası: {e}")


# ============================================================================
# MAIN ANALYSIS PAGE
# ============================================================================

class AnalysisPage:
    """Gelişmiş Portföy Analiz Sayfası - Dinamik Layout"""
    
    def __init__(
        self, 
        parent: ctk.CTkFrame, 
        db: 'Database', 
        api: Optional['APIService'] = None,
        theme: str = "dark"
    ):
        self.parent = parent
        self.db = db
        self.api = api
        self.theme = theme
        
        # State
        self.portfolio: List[Dict[str, Any]] = []
        self.filtered_portfolio: List[Dict[str, Any]] = []
        self.transactions: List[Dict[str, Any]] = []
        self.metrics: Optional[Any] = None
        
        # UI Components
        self.main_frame: Optional[ctk.CTkFrame] = None
        self.tabview: Optional[ctk.CTkTabview] = None
        self.period_var: Optional[ctk.StringVar] = None
        self.selected_stocks_var: Optional[ctk.StringVar] = None
        
        # Dynamic chart manager
        self.chart_manager = DynamicChartManager(theme=theme)
        
        # Lazy imports
        self._PortfolioMetrics = None
        self._charts = None
        
        # Loading state
        self._is_loading = False
        self._load_lock = threading.Lock()
        self._loading_label: Optional[ctk.CTkLabel] = None
        
        # Resize tracking
        self._resize_after_id = None
    
    @property
    def PortfolioMetrics(self):
        """Lazy load PortfolioMetrics"""
        if self._PortfolioMetrics is None:
            self._PortfolioMetrics = _import_metrics()
        return self._PortfolioMetrics
    
    @property
    def charts(self):
        """Lazy load chart modülleri"""
        if self._charts is None:
            self._charts = _import_charts()
        return self._charts
    
    # ========================================================================
    # LIFECYCLE
    # ========================================================================
    
    def create(self) -> None:
        """Ana sayfayı oluştur (Non-blocking)"""
        try:
            self.main_frame = ctk.CTkFrame(self.parent, fg_color="transparent")
            self.main_frame.pack(fill="both", expand=True)
            
            # Pencere resize olayını dinle
            self.parent.bind("<Configure>", self._on_window_resize)
            
            # Loading frame
            loading_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
            loading_frame.pack(expand=True)
            
            self._loading_label = ctk.CTkLabel(
                loading_frame,
                text="⏳ Veriler yükleniyor...",
                font=ctk.CTkFont(size=18, weight="bold")
            )
            self._loading_label.pack(pady=(0, 10))
            
            self._loading_progress = ctk.CTkProgressBar(loading_frame, width=300)
            self._loading_progress.pack(pady=10)
            self._loading_progress.set(0)
            
            self._loading_status = ctk.CTkLabel(
                loading_frame,
                text="Başlatılıyor...",
                font=ctk.CTkFont(size=12),
                text_color="gray"
            )
            self._loading_status.pack()
            
            # Verileri arka planda yükle
            def load_with_progress():
                try:
                    self._update_loading("Portföy verileri yükleniyor...", 0.2)
                    time.sleep(0.1)
                    
                    self.portfolio = self.db.get_portfolio() or []
                    self.transactions = self.db.get_transactions() or []
                    
                    self._update_loading("Güncel fiyatlar alınıyor...", 0.4)
                    time.sleep(0.1)
                    self._update_current_prices()
                    
                    self._update_loading("Metrikler hesaplanıyor...", 0.6)
                    time.sleep(0.1)
                    
                    self.filtered_portfolio = self.portfolio.copy()
                    
                    if self.portfolio:
                        self.metrics = self.PortfolioMetrics(self.portfolio, self.transactions, self.api)
                    else:
                        self.metrics = self.PortfolioMetrics([], [])
                    
                    self._update_loading("Arayüz hazırlanıyor...", 0.8)
                    time.sleep(0.1)
                    
                    self.parent.after(0, self._create_ui_safe)
                    
                except Exception as e:
                    print(f"Veri yükleme hatası: {e}")
                    import traceback
                    traceback.print_exc()
                    self.parent.after(0, lambda: self._show_error(f"Veri yüklenemedi: {e}"))
            
            thread = threading.Thread(target=load_with_progress, daemon=True)
            thread.start()
            
        except Exception as e:
            self._show_error(f"Sayfa oluşturulamadı: {e}")
    
    def _on_window_resize(self, event=None):
        """Pencere boyutu değiştiğinde grafikleri yenile"""
        if self._resize_after_id:
            self.parent.after_cancel(self._resize_after_id)
        
        # 200ms debounce
        self._resize_after_id = self.parent.after(200, self._handle_resize)
    
    def _handle_resize(self):
        """Resize işlemini gerçekleştir"""
        try:
            self.chart_manager.refresh_all()
        except Exception as e:
            print(f"Resize handle hatası: {e}")
    
    def _update_loading(self, message: str, progress: float) -> None:
        """Loading durumunu güncelle"""
        try:
            self.parent.after(0, lambda: self._loading_progress.set(progress))
            self.parent.after(0, lambda: self._loading_status.configure(text=message))
        except:
            pass
    
    def _create_ui_safe(self) -> None:
        """UI bileşenlerini güvenli şekilde oluştur"""
        try:
            # Loading'i kaldır
            if self._loading_label:
                self._loading_label.destroy()
            if hasattr(self, '_loading_progress'):
                self._loading_progress.destroy()
            if hasattr(self, '_loading_status'):
                self._loading_status.destroy()
            
            # Ana container temizle
            for widget in self.main_frame.winfo_children():
                widget.destroy()
            
            # UI bileşenlerini oluştur
            self._create_header()
            self._create_filter_bar()
            self._create_tabs()
            
            print("✓ UI başarıyla oluşturuldu")
            
        except Exception as e:
            print(f"UI oluşturma hatası: {e}")
            import traceback
            traceback.print_exc()
            self._show_error(f"Arayüz oluşturulamadı: {e}")
    
    def destroy(self) -> None:
        """Sayfayı temizle"""
        # Event binding'i kaldır
        try:
            self.parent.unbind("<Configure>")
        except:
            pass
        
        self.chart_manager.cleanup()
        if self.main_frame:
            self.main_frame.destroy()
    
    def refresh(self) -> None:
        """Sayfayı yenile"""
        with self._load_lock:
            if self._is_loading:
                return
            self._is_loading = True
        
        try:
            self.chart_manager.cleanup()
            self._load_data()
            self._refresh_current_tab()
        finally:
            self._is_loading = False
    
    # ========================================================================
    # DATA LOADING
    # ========================================================================
    
    def _load_data(self) -> None:
        """Verileri yükle"""
        try:
            self.portfolio = self.db.get_portfolio() or []
            self.transactions = self.db.get_transactions() or []
            self._update_current_prices()
            self.filtered_portfolio = self.portfolio.copy()
            
            if self.portfolio:
                self.metrics = self.PortfolioMetrics(self.portfolio, self.transactions, self.api)
            else:
                self.metrics = self.PortfolioMetrics([], [])
                
        except Exception as e:
            print(f"Veri yükleme hatası: {e}")
            self.portfolio = []
            self.transactions = []
            self.metrics = self.PortfolioMetrics([], [])
    
    def _update_current_prices(self) -> None:
        """Güncel fiyatları API'den al"""
        if not self.api or not self.portfolio:
            return
        
        try:
            symbols = [s['sembol'] for s in self.portfolio]
            prices = self.api.get_multiple_prices(symbols)
            
            for stock in self.portfolio:
                symbol = stock['sembol']
                if symbol in prices and prices[symbol] is not None:
                    stock['guncel_fiyat'] = prices[symbol]
                    
        except Exception as e:
            print(f"Fiyat güncelleme hatası: {e}")
    
    # ========================================================================
    # UI CREATION - RESPONSIVE LAYOUT
    # ========================================================================
    
    def _create_header(self) -> None:
        """Başlık oluştur"""
        header_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(5, 8), padx=10)
        
        ctk.CTkLabel(
            header_frame, 
            text="📊 Gelişmiş Portföy Analizi",
            font=ctk.CTkFont(size=26, weight="bold")
        ).pack(side="left")
        
        # Butonlar
        btn_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        btn_frame.pack(side="right")
        
        buttons = [
            ("💭 What-If", self._show_whatif, COLORS.get("cyan", "#17a2b8")),
            ("🔄 Yenile", self.refresh, None),
            ("📥 Export", self._export_report, COLORS.get("purple", "#6f42c1")),
        ]
        
        for text, command, color in buttons:
            btn = ctk.CTkButton(
                btn_frame, text=text, command=command,
                width=85, height=30, fg_color=color
            )
            btn.pack(side="left", padx=3)
    
    def _create_filter_bar(self) -> None:
        """Filtre çubuğu"""
        filter_frame = ctk.CTkFrame(
            self.main_frame, 
            fg_color=("gray85", "gray17"),
            corner_radius=8
        )
        filter_frame.pack(fill="x", pady=(0, 8), padx=10)
        
        content = ctk.CTkFrame(filter_frame, fg_color="transparent")
        content.pack(fill="x", padx=10, pady=6)
        
        # Dönem
        ctk.CTkLabel(content, text="📅 Dönem:", font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 6))
        
        self.period_var = ctk.StringVar(value=Period.DAYS_90.label)
        ctk.CTkComboBox(
            content,
            values=[p.label for p in Period],
            variable=self.period_var,
            width=100, height=26,
            command=lambda _: self._on_filter_change()
        ).pack(side="left", padx=(0, 12))
        
        # Hisse
        ctk.CTkLabel(content, text="📊 Hisseler:", font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 6))
        
        self.selected_stocks_var = ctk.StringVar(value="Tümü")
        stock_symbols = ["Tümü"] + [s['sembol'] for s in self.portfolio]
        
        ctk.CTkComboBox(
            content,
            values=stock_symbols,
            variable=self.selected_stocks_var,
            width=130, height=26,
            command=lambda _: self._on_filter_change()
        ).pack(side="left")
    
    def _create_tabs(self) -> None:
        """Sekmeleri oluştur"""
        self.tabview = ctk.CTkTabview(self.main_frame, corner_radius=8)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        
        for tab in TabName:
            self.tabview.add(tab.value)
        
        self._create_general_tab()
        self._create_performance_tab()
        self._create_risk_tab()
        self._create_comparison_tab()
        self._create_dividend_tab()
        
        self.tabview.set(TabName.GENERAL.value)
    
    # ========================================================================
    # GENERAL TAB - RESPONSIVE
    # ========================================================================
       
    def _create_kpi_cards(self, parent: ctk.CTkFrame) -> None:
        """KPI kartları - Responsive"""
        if not self.metrics:
            return
        
        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.pack(fill="x", pady=(0, 8))
        
        # Grid'i eşit dağıt
        for i in range(5):
            container.grid_columnconfigure(i, weight=1, uniform="kpi")
        
        kpis = self._calculate_kpis()
        
        for i, kpi in enumerate(kpis):
            card = ctk.CTkFrame(container, corner_radius=8, fg_color=("gray85", "gray17"))
            card.grid(row=0, column=i, padx=3, pady=4, sticky="nsew")
            
            content = ctk.CTkFrame(card, fg_color="transparent")
            content.pack(fill="both", expand=True, padx=8, pady=8)
            
            # İkon + başlık
            top = ctk.CTkFrame(content, fg_color="transparent")
            top.pack(fill="x")
            
            ctk.CTkLabel(top, text=kpi.icon, font=ctk.CTkFont(size=18)).pack(side="left", padx=(0, 5))
            ctk.CTkLabel(top, text=kpi.title, font=ctk.CTkFont(size=9), text_color="gray").pack(side="left")
            
            # Değer
            ctk.CTkLabel(
                content, text=kpi.value,
                font=ctk.CTkFont(size=18, weight="bold"),
                text_color=kpi.color
            ).pack(pady=(5, 1))
            
            # Alt
            ctk.CTkLabel(content, text=kpi.subtitle, font=ctk.CTkFont(size=8), text_color="gray").pack()
    
    def _calculate_kpis(self) -> List[KPIData]:
        """KPI değerlerini hesapla"""
        total_return = self._safe_calculate(self.metrics.calculate_total_return, 0.0)
        volatility = self._safe_calculate(self.metrics.calculate_volatility, 15.0)
        max_dd = self._safe_calculate(self.metrics.calculate_max_drawdown, 5.0)
        sharpe = self._safe_calculate(self.metrics.calculate_sharpe_ratio, 0.5)
        div_score = self._safe_calculate(self.metrics.calculate_diversification_score, 50.0)
        
        return [
            KPIData("📈" if total_return >= 0 else "📉", "Toplam Getiri", f"{total_return:+.2f}%", "Başlangıçtan",
                   COLORS["success"] if total_return >= 0 else COLORS["danger"]),
            KPIData("📊", "Volatilite", f"{volatility:.2f}%", "Yıllık",
                   COLORS["warning"] if volatility > 30 else COLORS["primary"]),
            KPIData("⚠️", "Maks Düşüş", f"{max_dd:.2f}%", "En kötü zarar",
                   COLORS["danger"] if max_dd > 20 else COLORS["warning"]),
            KPIData("🎯", "Sharpe Oranı", f"{sharpe:.2f}", "Risk/Getiri",
                   COLORS["success"] if sharpe > 1 else COLORS["primary"]),
            KPIData("🌈", "Çeşitlendirme", f"{div_score:.0f}/100", "Diversifikasyon",
                   COLORS["purple"] if div_score > 70 else COLORS["warning"])
        ]
    
    def _create_general_tab(self) -> None:
        """Genel Bakış Sekmesi - Büyük containerlar ve tam sığan grafikler"""
        tab = self.tabview.tab(TabName.GENERAL.value)
        
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=3, pady=3)
        
        # KPI Kartları
        self._create_kpi_cards(scroll)
        
        # Ana pencerenin yüksekliğine göre container boyutlarını ayarla
        window_height = self.parent.winfo_height()
        charts_height = int(window_height * 0.35)  # %35 yükseklik - Sektör ve Portföy
        profit_height = int(window_height * 0.30)  # %30 yükseklik - Kar/Zarar
        
        # Grafikler için büyük container
        charts_container = ctk.CTkFrame(scroll, fg_color="transparent")
        charts_container.pack(fill="both", expand=True, pady=8)
        
        # Grid layout - eşit iki sütun
        charts_container.grid_columnconfigure(0, weight=1)
        charts_container.grid_columnconfigure(1, weight=1)
        charts_container.grid_rowconfigure(0, weight=1)
        
        # 1. Sektör Dağılımı - BÜYÜK FRAME
        left_frame = ctk.CTkFrame(
            charts_container,
            fg_color=("gray90", "gray13"),
            corner_radius=8,
            height=charts_height  # Sabit yüksek boyut
        )
        left_frame.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        left_frame.pack_propagate(False)  # Boyutu koru!
        
        # 2. Portföy Dağılımı - BÜYÜK FRAME
        right_frame = ctk.CTkFrame(
            charts_container,
            fg_color=("gray90", "gray13"),
            corner_radius=8,
            height=charts_height  # Sabit yüksek boyut
        )
        right_frame.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        right_frame.pack_propagate(False)  # Boyutu koru!
        
        # 3. Kar/Zarar Bar - BÜYÜK FRAME
        bottom_frame = ctk.CTkFrame(
            scroll,
            fg_color=("gray90", "gray13"),
            corner_radius=8,
            height=profit_height  # Sabit yüksek boyut
        )
        bottom_frame.pack(fill="both", expand=True, pady=8, padx=4)
        bottom_frame.pack_propagate(False)  # Boyutu koru!
        
        # Grafikleri oluştur - Container'a tam sığacak şekilde
        self._create_sector_pie_fullsize(left_frame)
        self._create_portfolio_treemap_fullsize(right_frame)
        self._create_profit_loss_bar_fullsize(bottom_frame)


    def _create_sector_pie_fullsize(self, container: ctk.CTkFrame) -> None:
        """Sektör pasta grafiği - Container'a tam sığacak versiyon"""
        if not self.filtered_portfolio:
            self._show_empty_message(container, "Portföy boş")
            return
        
        try:
            from utils.sector_mapper import get_all_sectors
            sectors = get_all_sectors(self.filtered_portfolio)
            
            sector_values = {}
            for sector, stocks in sectors.items():
                total = sum(s['adet'] * s.get('guncel_fiyat', s['ort_maliyet']) for s in stocks)
                if total > 0:
                    sector_values[sector] = total
            
            if not sector_values:
                self._show_empty_message(container, "Sektör verisi yok")
                return
            
            # Küçük sektörleri "Diğer" altında topla
            sorted_sectors = sorted(sector_values.items(), key=lambda x: x[1], reverse=True)
            threshold = sum(sector_values.values()) * 0.02
            main_sectors = {}
            other_total = 0
            
            for sector, value in sorted_sectors:
                if value > threshold and len(main_sectors) < 8:  # Max 8 ana sektör
                    main_sectors[sector] = value
                else:
                    other_total += value
            
            if other_total > 0:
                main_sectors["Diğer"] = other_total
            
            # Container boyutunu al
            container.update_idletasks()
            width = container.winfo_width()
            height = container.winfo_height()
            
            # Figure oluştur - container boyutuna göre
            fig = matplotlib.figure.Figure(figsize=(width/100, height/100), dpi=100)
            
            # Tema ayarları
            if self.theme == "dark":
                fig.patch.set_facecolor('#2b2b2b')
                text_color = 'white'
            else:
                fig.patch.set_facecolor('#f0f0f0')
                text_color = 'black'
            
            # Subplot - manuel pozisyon
            ax = fig.add_subplot(111)
            
            # Güzel renkler
            colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7', '#DDA0DD', 
                      '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E2', '#F8B739', '#52B788']
            
            # Pasta grafiği
            wedges, texts, autotexts = ax.pie(
                list(main_sectors.values()),
                labels=None,  # Etiketleri dışarıda göstereceğiz
                autopct='%1.1f%%',
                colors=colors[:len(main_sectors)],
                startangle=90,
                pctdistance=0.85,
                explode=[0.02] * len(main_sectors)  # Hafif ayrık
            )
            
            # Font boyutu - container'a göre
            font_size = max(8, min(11, int(height/65)))
            
            # Yüzde yazıları - HER ZAMAN BEYAZ
            for autotext in autotexts:
                autotext.set_color('white')
                autotext.set_fontsize(font_size)
                autotext.set_weight('bold')
            
            # Başlık - TEMA UYUMLU
            ax.set_title('Sektör Dağılımı', fontsize=font_size+2, 
                        fontweight='bold', color=text_color, pad=15)
            
            # Legend - Sağ tarafta, değerlerle birlikte
            legend_labels = []
            total = sum(main_sectors.values())
            for sector, value in main_sectors.items():
                pct = (value / total) * 100
                legend_labels.append(f'{sector}\n{value:,.0f}₺ ({pct:.1f}%)')
            
            legend = ax.legend(
                wedges, 
                legend_labels,
                title="Sektörler",
                loc="center left",
                bbox_to_anchor=(1, 0, 0.3, 1),
                fontsize=font_size-1,
                title_fontsize=font_size,
                frameon=False
            )
            
            # Legend text - TEMA UYUMLU - DÜZELTME BURADA
            # Doğru yöntem: set_title_fontproperties yerine title özelliğini kullan
            legend.get_title().set_color(text_color)
            legend.get_title().set_size(font_size)
            legend.get_title().set_weight('bold')
            
            # Legend text renkleri
            for text in legend.get_texts():
                text.set_color(text_color)
            
            # Tight layout
            fig.tight_layout(pad=0.5)
            
            # Canvas
            canvas = FigureCanvasTkAgg(fig, container)
            canvas.draw()
            canvas_widget = canvas.get_tk_widget()
            canvas_widget.pack(fill="both", expand=True)
            
        except Exception as e:
            print(f"Sector pie hatası: {e}")
            import traceback
            traceback.print_exc()
            self._show_empty_message(container, "Grafik oluşturulamadı")


    def _create_portfolio_treemap_fullsize(self, container: ctk.CTkFrame) -> None:
        """Portföy treemap - Container'a tam sığacak versiyon"""
        if not self.filtered_portfolio:
            self._show_empty_message(container, "Portföy boş")
            return
        
        try:
            # Squarify kütüphanesini import et
            try:
                import squarify
                HAS_SQUARIFY = True
            except ImportError:
                HAS_SQUARIFY = False
                print("squarify yüklü değil, alternatif görselleştirme kullanılacak")
            
            # Container boyutunu al
            container.update_idletasks()
            width = container.winfo_width()
            height = container.winfo_height()
            
            # Figure oluştur - container boyutuna göre
            fig = matplotlib.figure.Figure(figsize=(width/100, height/100), dpi=100)
            
            # Tema ayarları
            if self.theme == "dark":
                fig.patch.set_facecolor('#2b2b2b')
                text_color = 'white'
                bg_color = '#2b2b2b'
            else:
                fig.patch.set_facecolor('#f0f0f0')
                text_color = 'black'
                bg_color = '#fafafa'
            
            # Verileri hazırla
            symbols = []
            values = []
            profits = []
            
            for s in self.filtered_portfolio:
                value = s['adet'] * s.get('guncel_fiyat', s['ort_maliyet'])
                if value > 0:  # Sadece pozitif değerleri al
                    symbols.append(s['sembol'])
                    values.append(value)
                    profit_pct = ((s.get('guncel_fiyat', s['ort_maliyet']) - s['ort_maliyet']) / s['ort_maliyet'] * 100)
                    profits.append(profit_pct)
            
            if not values:
                self._show_empty_message(container, "Geçerli veri yok")
                return
            
            # Font boyutu - container'a göre
            font_size = max(8, min(10, int(height/65)))
            
            # Toplam değer
            total_value = sum(values)
            
            # Subplot
            ax = fig.add_subplot(111)
            ax.set_facecolor(bg_color)
            
            if HAS_SQUARIFY:
                # Renkleri kar/zarara göre ayarla
                colors = []
                for p in profits:
                    if p > 10:
                        colors.append('#00b894')  # Koyu yeşil
                    elif p > 5:
                        colors.append('#55efc4')  # Yeşil
                    elif p > 0:
                        colors.append('#81ecec')  # Açık yeşil
                    elif p > -5:
                        colors.append('#fab1a0')  # Açık kırmızı
                    elif p > -10:
                        colors.append('#ff7675')  # Kırmızı
                    else:
                        colors.append('#d63031')  # Koyu kırmızı
                
                # Etiketleri hazırla
                labels = []
                for sym, val, prof in zip(symbols, values, profits):
                    pct = (val / total_value) * 100
                    labels.append(f'{sym}\n{val:,.0f}₺\n({pct:.1f}%)\n{prof:+.1f}%')
                
                # Treemap çiz
                squarify.plot(
                    sizes=values,
                    label=labels,
                    color=colors,
                    alpha=0.8,
                    text_kwargs={'fontsize': font_size, 'weight': 'bold', 'color': 'white'},
                    ax=ax,
                    bar_kwargs={'linewidth': 2, 'edgecolor': 'white'}
                )
                
                ax.axis('off')
                
            else:
                # Squarify yoksa pie chart alternatifi
                # Renkleri kar/zarara göre ayarla
                colors = []
                for p in profits:
                    if p > 0:
                        # Yeşil tonları
                        intensity = min(p / 20, 1)
                        colors.append((0.2, 0.7 + 0.3*intensity, 0.2))
                    else:
                        # Kırmızı tonları
                        intensity = min(abs(p) / 20, 1)
                        colors.append((0.7 + 0.3*intensity, 0.2, 0.2))
                
                # Pasta grafiği olarak göster
                wedges, texts, autotexts = ax.pie(
                    values,
                    labels=symbols,
                    colors=colors,
                    autopct=lambda pct: f'{pct:.1f}%\n({pct*total_value/100:,.0f}₺)',
                    startangle=90,
                    textprops={'fontsize': font_size, 'color': text_color}
                )
                
                # Performans bilgilerini legend'de göster
                legend_labels = [f'{sym}: {prof:+.1f}%' for sym, prof in zip(symbols, profits)]
                legend = ax.legend(wedges, legend_labels, 
                          title="Kar/Zarar %",
                          loc="center left",
                          bbox_to_anchor=(1, 0, 0.5, 1),
                          fontsize=font_size-1)
                
                # Legend text - TEMA UYUMLU
                legend.get_title().set_color(text_color)
                for text in legend.get_texts():
                    text.set_color(text_color)
            
            # Başlık
            ax.set_title('Portföy Dağılımı ve Performans', fontsize=font_size+2, 
                        fontweight='bold', color=text_color, pad=15)
            
            # Tight layout
            fig.tight_layout(pad=0.5)
            
            # Canvas
            canvas = FigureCanvasTkAgg(fig, container)
            canvas.draw()
            canvas_widget = canvas.get_tk_widget()
            canvas_widget.pack(fill="both", expand=True)
            
        except Exception as e:
            print(f"Portfolio treemap hatası: {e}")
            self._show_empty_message(container, "Grafik oluşturulamadı")


    def _create_profit_loss_bar_fullsize(self, container: ctk.CTkFrame) -> None:
        """Kar/Zarar bar - Container'a tam sığacak versiyon"""
        if not self.filtered_portfolio:
            self._show_empty_message(container, "Portföy boş")
            return
        
        try:
            # Container boyutunu al
            container.update_idletasks()
            width = container.winfo_width()
            height = container.winfo_height()
            
            # Figure oluştur - container boyutuna göre
            fig = matplotlib.figure.Figure(figsize=(width/100, height/100), dpi=100)
            
            # Tema ayarları
            if self.theme == "dark":
                fig.patch.set_facecolor('#2b2b2b')
                text_color = 'white'
                grid_color = '#555555'
                bg_color = '#2b2b2b'
            else:
                fig.patch.set_facecolor('#f0f0f0')
                text_color = 'black'
                grid_color = '#cccccc'
                bg_color = '#fafafa'
            
            # Verileri hazırla
            data = []
            for stock in self.filtered_portfolio:
                symbol = stock['sembol']
                profit = (stock.get('guncel_fiyat', stock['ort_maliyet']) - stock['ort_maliyet']) * stock['adet']
                data.append((symbol, profit))
            
            # Kar/zarara göre sırala
            data.sort(key=lambda x: x[1])
            
            symbols = [d[0] for d in data]
            profits = [d[1] for d in data]
            
            # Subplot - manuel pozisyon
            ax = fig.add_subplot(111)
            ax.set_facecolor(bg_color)
            
            # Renkler
            colors = ['#00b894' if p >= 0 else '#d63031' for p in profits]
            
            # Font boyutu - container'a göre
            font_size = max(8, min(11, int(height/50)))
            
            y_pos = np.arange(len(symbols))
            bars = ax.barh(y_pos, profits, color=colors, height=0.6, 
                          edgecolor='white', linewidth=1)
            
            # Sıfır çizgisi
            ax.axvline(x=0, color=text_color, linestyle='-', linewidth=1, alpha=0.5)
            
            # Y ekseni
            ax.set_yticks(y_pos)
            ax.set_yticklabels(symbols, fontsize=font_size, color=text_color, weight='bold')
            ax.invert_yaxis()
            
            # Değer etiketleri - TEMA UYUMLU
            for bar, profit in zip(bars, profits):
                width = bar.get_width()
                label_x = width + (max(abs(p) for p in profits) * 0.02 * (1 if width >= 0 else -1))
                
                ax.text(label_x, bar.get_y() + bar.get_height()/2,
                       f'{profit:+,.0f}₺',
                       ha='left' if profit >= 0 else 'right',
                       va='center',
                       fontsize=font_size,
                       color='#00b894' if profit >= 0 else '#d63031',
                       weight='bold')
            
            # Eksen ayarları - TEMA UYUMLU
            ax.set_xlabel('Kar/Zarar (₺)', fontsize=font_size+1, color=text_color, weight='bold')
            ax.set_title('Hisse Bazında Kar/Zarar Durumu', fontsize=font_size+2, 
                        fontweight='bold', color=text_color, pad=15)
            
            # Grid
            ax.grid(True, axis='x', alpha=0.2, color=grid_color)
            ax.set_axisbelow(True)
            
            # X ekseni formatı
            ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:+,.0f}'))
            ax.tick_params(labelsize=font_size, colors=text_color)
            
            # Tight layout
            fig.tight_layout(pad=0.5)
            
            # Canvas
            canvas = FigureCanvasTkAgg(fig, container)
            canvas.draw()
            canvas_widget = canvas.get_tk_widget()
            canvas_widget.pack(fill="both", expand=True)
            
        except Exception as e:
            print(f"Profit loss bar hatası: {e}")
            self._show_empty_message(container, "Grafik oluşturulamadı")

    def _create_risk_tab(self) -> None:
        """Risk sekmesi - Çok geniş containerlar"""
        tab = self.tabview.tab(TabName.RISK.value)
        
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=3, pady=3)
        
        ctk.CTkLabel(
            scroll, 
            text="⚠️ Risk Analizi", 
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=(0, 10))
        
        # BÜYÜK Korelasyon container - 700px yükseklik
        corr_frame = ctk.CTkFrame(
            scroll,
            fg_color=("gray90", "gray13"),
            corner_radius=8,
            height=1000  # ÇOK BÜYÜK
        )
        corr_frame.pack(fill="both", expand=True, padx=4, pady=4)
        corr_frame.pack_propagate(False)  # Boyutu sabitle
        
        if len(self.portfolio) >= 2:
            self._create_correlation_matrix_large(corr_frame)
        else:
            self._show_empty_message(corr_frame, "Korelasyon için en az 2 hisse gerekli")
        
        # BÜYÜK Volatilite container - 500px yükseklik
        risk_frame = ctk.CTkFrame(
            scroll,
            fg_color=("gray90", "gray13"),
            corner_radius=8,
            height=1000  # ÇOK BÜYÜK
        )
        risk_frame.pack(fill="both", expand=True, pady=(10, 4), padx=4)
        risk_frame.pack_propagate(False)  # Boyutu sabitle
        
        self._create_risk_distribution_large(risk_frame)


# pages/analysis_page.py - Risk tabı - TAM CONTAINER DOLDURAN VERSİYON

    def _create_correlation_matrix_large(self, container: ctk.CTkFrame) -> None:
        """Korelasyon matrisi - Container'ı TAM DOLDURAN versiyon"""
        if not self.api:
            self._show_empty_message(container, "API bağlantısı gerekli")
            return
        
        try:
            # En fazla 10 hisse
            symbols = [s['sembol'] for s in self.portfolio[:10]]
            
            if len(symbols) < 2:
                self._show_empty_message(container, "En az 2 hisse gerekli")
                return
            
            price_data = {}
            
            for symbol in symbols:
                historical = self.api.get_historical_data(symbol, 90)
                
                if is_dataframe_valid(historical):
                    price_col = next((col for col in ['HISSE_KAPANIS', 'Close', 'close', 'Kapanış'] 
                                     if col in historical.columns), None)
                    
                    if price_col:
                        price_data[symbol] = historical[price_col].values.tolist()
            
            if len(price_data) < 2:
                self._show_empty_message(container, "Yeterli veri yok")
                return
            
            min_len = min(len(v) for v in price_data.values())
            df = pd.DataFrame({k: v[-min_len:] for k, v in price_data.items()})
            corr = df.pct_change().corr()
            
            # Container boyutunu al ve figure'ı buna göre ayarla
            container.update_idletasks()
            container_width = max(container.winfo_width(), 800)
            container_height = max(container.winfo_height(), 700)
            
            # Figure boyutunu hesapla - Container'ı TAM DOLDUR
            dpi = 100
            # Padding'leri çıkar
            padding_x = 40
            padding_y = 80  # Başlık ve bilgi için
            
            fig_width = (container_width - padding_x) / dpi
            fig_height = (container_height - padding_y) / dpi
            
            # Minimum boyutlar
            fig_width = max(fig_width, 10)
            fig_height = max(fig_height, 8)
            
            # Figure oluştur
            fig = plt.Figure(figsize=(fig_width, fig_height), dpi=dpi)
            
            if self.theme == "dark":
                fig.patch.set_facecolor('#2b2b2b')
                text_color = 'white'
                grid_color = 'white'
            else:
                fig.patch.set_facecolor('#f0f0f0')
                text_color = 'black'
                grid_color = 'black'
            
            # Subplot - manuel pozisyon ayarla (tüm alanı kullan)
            ax = fig.add_axes([0.08, 0.08, 0.72, 0.85])  # [left, bottom, width, height]
            
            # Korelasyon matrisi - ASPECT AUTO (tam doldur)
            im = ax.imshow(corr.values, cmap='RdYlGn', vmin=-1, vmax=1, aspect='auto')  # AUTO!
            
            # Tick'ler
            ax.set_xticks(np.arange(len(corr.columns)))
            ax.set_yticks(np.arange(len(corr.columns)))
            
            # Font boyutları - dinamik
            num_stocks = len(corr.columns)
            if num_stocks <= 5:
                label_fontsize = 16
                value_fontsize = 14
            elif num_stocks <= 8:
                label_fontsize = 14
                value_fontsize = 12
            else:
                label_fontsize = 12
                value_fontsize = 10
            
            ax.set_xticklabels(corr.columns, fontsize=label_fontsize, color=text_color, weight='bold')
            ax.set_yticklabels(corr.columns, fontsize=label_fontsize, color=text_color, weight='bold')
            
            # X etiketlerini döndür
            plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")
            
            # Değerleri yaz
            for i in range(len(corr.columns)):
                for j in range(len(corr.columns)):
                    value = corr.iloc[i, j]
                    
                    # Text rengi
                    if abs(value) > 0.5:
                        txt_color = 'white'
                    else:
                        txt_color = 'black'
                    
                    ax.text(j, i, f'{value:.2f}',
                           ha="center", va="center",
                           color=txt_color, fontsize=value_fontsize, weight='bold')
            
            # Başlık
            fig.suptitle('Hisse Korelasyon Matrisi', fontsize=18, fontweight='bold', 
                        color=text_color, y=0.98)
            
            # Colorbar - sağ tarafa manuel yerleştir
            cbar_ax = fig.add_axes([0.82, 0.08, 0.03, 0.85])
            cbar = fig.colorbar(im, cax=cbar_ax)
            cbar.set_label('Korelasyon', fontsize=14, color=text_color, weight='bold')
            cbar.ax.tick_params(labelsize=12, colors=text_color)
            
            # Grid çizgileri
            ax.set_xticks(np.arange(len(corr.columns)+1)-.5, minor=True)
            ax.set_yticks(np.arange(len(corr.columns)+1)-.5, minor=True)
            ax.grid(which="minor", color=grid_color, linestyle='-', linewidth=1, alpha=0.4)
            ax.tick_params(which="minor", size=0)
            
            # Arka plan
            if self.theme == "dark":
                ax.set_facecolor('#2b2b2b')
            else:
                ax.set_facecolor('#fafafa')
            
            # Canvas - TAM BOYUT
            canvas = FigureCanvasTkAgg(fig, container)
            canvas.draw()
            widget = canvas.get_tk_widget()
            widget.pack(fill="both", expand=True, padx=5, pady=5)
            
            # Bilgi kutusu - ALT
            info_frame = ctk.CTkFrame(container, fg_color="transparent", height=40)
            info_frame.pack(fill="x", side="bottom", padx=15, pady=(0, 10))
            info_frame.pack_propagate(False)
            
            info_text = "🟢 Yeşil: Pozitif korelasyon | 🔴 Kırmızı: Negatif korelasyon | ⚪ Sarı: Düşük korelasyon"
            
            ctk.CTkLabel(
                info_frame,
                text=info_text,
                font=ctk.CTkFont(size=11),
                text_color="gray"
            ).pack(expand=True)
            
        except Exception as e:
            print(f"Korelasyon hatası: {e}")
            import traceback
            traceback.print_exc()
            self._show_empty_message(container, "Korelasyon hesaplanamadı")


    def _create_risk_distribution_large(self, container: ctk.CTkFrame) -> None:
        """Risk dağılımı - Container'ı TAM DOLDURAN versiyon"""
        if not self.filtered_portfolio:
            self._show_empty_message(container, "Portföy boş")
            return
        
        try:
            # Verileri hazırla
            data = []
            for stock in self.filtered_portfolio:
                symbol = stock['sembol']
                
                if self.api:
                    try:
                        vol = self.api.calculate_volatility(symbol, 30)
                        if not vol or vol <= 0:
                            vol = 25.0
                    except:
                        vol = 25.0
                else:
                    vol = 25.0
                
                data.append((symbol, vol))
            
            # Sırala
            data.sort(key=lambda x: x[1], reverse=True)
            
            # Max 20 hisse
            if len(data) > 20:
                data = data[:20]
            
            symbols = [d[0] for d in data]
            volatilities = [d[1] for d in data]
            
            # Container boyutunu al
            container.update_idletasks()
            container_width = max(container.winfo_width(), 800)
            container_height = max(container.winfo_height(), 500)
            
            # Figure boyutunu hesapla - TAM DOLDUR
            dpi = 100
            padding_x = 40
            padding_y = 60
            
            fig_width = (container_width - padding_x) / dpi
            fig_height = (container_height - padding_y) / dpi
            
            fig_width = max(fig_width, 10)
            fig_height = max(fig_height, 6)
            
            # Figure oluştur
            fig = plt.Figure(figsize=(fig_width, fig_height), dpi=dpi)
            
            if self.theme == "dark":
                fig.patch.set_facecolor('#2b2b2b')
                text_color = 'white'
                grid_color = '#555555'
            else:
                fig.patch.set_facecolor('#f0f0f0')
                text_color = 'black'
                grid_color = '#cccccc'
            
            # Subplot - manuel pozisyon (tüm alanı kullan)
            ax = fig.add_axes([0.12, 0.08, 0.85, 0.85])  # Geniş alan
            
            # Renklendirme
            colors = []
            for v in volatilities:
                if v > 40:
                    colors.append('#e74c3c')
                elif v > 25:
                    colors.append('#f39c12')
                else:
                    colors.append('#2ecc71')
            
            y_pos = np.arange(len(symbols))
            
            # Bar yüksekliği - dinamik
            bar_height = min(0.75, 12.0 / len(symbols))
            
            bars = ax.barh(y_pos, volatilities, color=colors, height=bar_height, 
                          edgecolor='white', linewidth=1)
            
            # Y ekseni
            ax.set_yticks(y_pos)
            ax.set_yticklabels(symbols, fontsize=13, color=text_color, weight='bold')
            ax.invert_yaxis()
            
            # Değer etiketleri
            for i, (bar, vol) in enumerate(zip(bars, volatilities)):
                bar_width = bar.get_width()
                
                # Bar içinde değer (eğer yeterince geniş ise)
                if bar_width > max(volatilities) * 0.15:
                    ax.text(bar_width / 2, bar.get_y() + bar.get_height()/2,
                           f'{vol:.1f}%',
                           ha='center', va='center',
                           fontsize=11, color='white', weight='bold')
                
                # Bar dışında risk seviyesi
                risk_level = "⚠️ Yüksek" if vol > 40 else "⚡ Orta" if vol > 25 else "✅ Düşük"
                ax.text(bar_width + max(volatilities) * 0.02, 
                       bar.get_y() + bar.get_height()/2,
                       f'{vol:.1f}% {risk_level}',
                       ha='left', va='center',
                       fontsize=10, color=colors[i], weight='bold')
            
            # Eksen ayarları
            ax.set_xlabel('Volatilite (Yıllık %)', fontsize=14, color=text_color, weight='bold')
            
            # Başlık - üstte
            fig.suptitle('Hisse Bazında Risk Dağılımı (30 Günlük Volatilite)', 
                        fontsize=18, fontweight='bold', color=text_color, y=0.98)
            
            # Risk bölgeleri - arka plan
            max_vol = max(volatilities) if volatilities else 50
            ax.axvspan(0, 25, alpha=0.08, color='green', zorder=0)
            ax.axvspan(25, 40, alpha=0.08, color='orange', zorder=0)
            ax.axvspan(40, max_vol * 1.15, alpha=0.08, color='red', zorder=0)
            
            # Referans çizgileri
            ax.axvline(x=25, color='green', linestyle='--', linewidth=1, alpha=0.5)
            ax.axvline(x=40, color='red', linestyle='--', linewidth=1, alpha=0.5)
            
            # Grid
            ax.grid(True, axis='x', alpha=0.3, color=grid_color, linestyle='-', linewidth=0.5)
            ax.set_axisbelow(True)
            
            # X ekseni limitleri
            ax.set_xlim(0, max_vol * 1.2)
            
            # Legend - sağ alt
            from matplotlib.patches import Patch
            legend_elements = [
                Patch(facecolor='#2ecc71', label='✅ Düşük: 0-25%'),
                Patch(facecolor='#f39c12', label='⚡ Orta: 25-40%'),
                Patch(facecolor='#e74c3c', label='⚠️ Yüksek: >40%')
            ]
            ax.legend(handles=legend_elements, loc='lower right', fontsize=11, 
                     framealpha=0.95, edgecolor=text_color)
            
            # Arka plan
            if self.theme == "dark":
                ax.set_facecolor('#2b2b2b')
            else:
                ax.set_facecolor('#fafafa')
            
            ax.tick_params(labelsize=12, colors=text_color)
            
            # Canvas - TAM BOYUT
            canvas = FigureCanvasTkAgg(fig, container)
            canvas.draw()
            widget = canvas.get_tk_widget()
            widget.pack(fill="both", expand=True, padx=5, pady=5)
            
        except Exception as e:
            print(f"Risk dağılımı hatası: {e}")
            import traceback
            traceback.print_exc()
            self._show_empty_message(container, "Grafik oluşturulamadı")


    def _create_profit_loss_bar(self, container: ctk.CTkFrame) -> None:
        """Kar/Zarar bar - Daha net"""
        if not self.filtered_portfolio:
            self._show_empty_message(container, "Portföy boş")
            return
        
        try:
            # Büyük figure
            fig = plt.Figure(figsize=(12, 6), dpi=80)
            fig.patch.set_facecolor('none')
            
            if self.theme == "dark":
                fig.patch.set_facecolor('#2b2b2b')
                text_color = 'white'
                grid_color = '#555555'
            else:
                fig.patch.set_facecolor('#f0f0f0')
                text_color = 'black'
                grid_color = '#cccccc'
            
            ax = fig.add_subplot(111)
            
            # Verileri hazırla
            data = []
            for stock in self.filtered_portfolio:
                symbol = stock['sembol']
                profit = (stock.get('guncel_fiyat', stock['ort_maliyet']) - stock['ort_maliyet']) * stock['adet']
                data.append((symbol, profit))
            
            # Kar/zarara göre sırala
            data.sort(key=lambda x: x[1])
            
            symbols = [d[0] for d in data]
            profits = [d[1] for d in data]
            
            # Renkler
            colors = ['#00b894' if p >= 0 else '#d63031' for p in profits]
            
            y_pos = np.arange(len(symbols))
            bars = ax.barh(y_pos, profits, color=colors, height=0.6)
            
            # Sıfır çizgisi
            ax.axvline(x=0, color=text_color, linestyle='-', linewidth=1, alpha=0.5)
            
            # Y ekseni
            ax.set_yticks(y_pos)
            ax.set_yticklabels(symbols, fontsize=11, color=text_color, weight='bold')
            ax.invert_yaxis()
            
            # Değer etiketleri
            for bar, profit in zip(bars, profits):
                width = bar.get_width()
                label_x = width + (max(abs(p) for p in profits) * 0.02 * (1 if width >= 0 else -1))
                
                ax.text(label_x, bar.get_y() + bar.get_height()/2,
                       f'{profit:+,.0f}₺',
                       ha='left' if profit >= 0 else 'right',
                       va='center',
                       fontsize=10,
                       color='#00b894' if profit >= 0 else '#d63031',
                       weight='bold')
            
            ax.set_xlabel('Kar/Zarar (₺)', fontsize=12, color=text_color, weight='bold')
            ax.set_title('Hisse Bazında Kar/Zarar Durumu', fontsize=14, fontweight='bold', 
                        color=text_color, pad=20)
            
            # Grid
            ax.grid(True, axis='x', alpha=0.2, color=grid_color)
            ax.set_axisbelow(True)
            
            # X ekseni formatı
            ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:+,.0f}'))
            ax.tick_params(labelsize=10, colors=text_color)
            
            # Arka plan
            if self.theme == "dark":
                ax.set_facecolor('#2b2b2b')
            else:
                ax.set_facecolor('#fafafa')
            
            fig.tight_layout()
            
            canvas = FigureCanvasTkAgg(fig, container)
            canvas.draw()
            widget = canvas.get_tk_widget()
            widget.pack(fill="both", expand=True, padx=5, pady=5)
            
        except Exception as e:
            print(f"Profit loss bar hatası: {e}")
            self._show_empty_message(container, "Grafik oluşturulamadı")
    
    # ========================================================================
    # PERFORMANCE TAB - RESPONSIVE
    # ========================================================================
    
    def _create_performance_tab(self) -> None:
        """Performans sekmesi - Dinamik"""
        tab = self.tabview.tab(TabName.PERFORMANCE.value)
        
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=3, pady=3)
        
        self._create_period_returns(scroll)
        
        # Dinamik chart frame
        chart_frame = self.chart_manager.create_responsive_frame(
            scroll,
            min_height=250,
            aspect_ratio=2.5
        )
        chart_frame.pack(fill="both", expand=True, pady=8, padx=4)
        self._create_portfolio_value_chart(chart_frame)
    
    def _create_period_returns(self, parent: ctk.CTkFrame) -> None:
        """Dönemsel getiri kartları - Responsive"""
        if not self.metrics:
            return
        
        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.pack(fill="x", pady=(0, 8))
        
        for i in range(4):
            container.grid_columnconfigure(i, weight=1, uniform="period")
        
        periods = [("30 Gün", 30), ("90 Gün", 90), ("6 Ay", 180), ("1 Yıl", 365)]
        
        for i, (label, days) in enumerate(periods):
            value = self._safe_calculate(lambda d=days: self.metrics.calculate_period_return(d), 0.0)
            
            card = ctk.CTkFrame(container, corner_radius=8, fg_color=("gray85", "gray17"))
            card.grid(row=0, column=i, padx=3, pady=4, sticky="nsew")
            
            color = COLORS["success"] if value >= 0 else COLORS["danger"]
            icon = "📈" if value >= 0 else "📉"
            
            ctk.CTkLabel(card, text=icon, font=ctk.CTkFont(size=24)).pack(pady=(10, 3))
            ctk.CTkLabel(card, text=label, font=ctk.CTkFont(size=10), text_color="gray").pack()
            ctk.CTkLabel(card, text=f"{value:+.2f}%", font=ctk.CTkFont(size=17, weight="bold"), text_color=color).pack(pady=(3, 10))
    
    def _create_portfolio_value_chart(self, container: ResponsiveChartFrame) -> None:
        """Portföy değeri grafiği - Dinamik"""
        period = Period.from_label(self.period_var.get() if self.period_var else "90 Gün")
        days = period.days if period.days > 0 else 365
        
        dates, values, cost_line = self._get_portfolio_history(days)
        
        if not dates or not values:
            self._show_empty_message(container, "Portföy geçmişi bulunamadı")
            return
        
        try:
            fig, ax = self.chart_manager.create_dynamic_figure(container)
            
            ax.plot(dates, values, 'b-', linewidth=1.5, label='Portföy Değeri')
            ax.axhline(y=cost_line, color='orange', linestyle='--', linewidth=1, label='Maliyet')
            ax.fill_between(dates, values, cost_line, alpha=0.2, 
                           color='green' if values[-1] >= cost_line else 'red')
            
            ax.set_xlabel('Tarih', fontsize=9)
            ax.set_ylabel('Değer (₺)', fontsize=9)
            ax.set_title(f'Portföy Değeri (Son {days} Gün)', fontsize=11, fontweight='bold')
            ax.legend(fontsize=8, loc='best')
            ax.grid(True, alpha=0.2)
            ax.tick_params(labelsize=8)
            
            # Tarih formatı
            import matplotlib.dates as mdates
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
            ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
            
            fig.tight_layout(pad=0.5)
            self.chart_manager.embed_figure(fig, container)
            
        except Exception as e:
            print(f"Portfolio value chart hatası: {e}")
            self._show_empty_message(container, "Grafik oluşturulamadı")
    
    def _get_portfolio_history(self, days: int) -> Tuple[List[datetime], List[float], float]:
        """Portföy geçmişi al"""
        if not self.api or not self.filtered_portfolio:
            return self._generate_simulated_history(days)
        
        try:
            all_data = {}
            
            for stock in self.filtered_portfolio:
                symbol = stock['sembol']
                historical = self.api.get_historical_data(symbol, days)
                
                if is_dataframe_valid(historical):
                    price_col = None
                    for col in ['HISSE_KAPANIS', 'Close', 'close', 'Kapanış']:
                        if col in historical.columns:
                            price_col = col
                            break
                    
                    if price_col:
                        if not isinstance(historical.index, pd.DatetimeIndex):
                            historical.index = pd.to_datetime(historical.index)
                        
                        price_dict = {date: safe_float(price) for date, price in zip(historical.index, historical[price_col])}
                        all_data[symbol] = price_dict
            
            if not all_data:
                return self._generate_simulated_history(days)
            
            all_dates = set()
            for data in all_data.values():
                all_dates.update(data.keys())
            
            sorted_dates = sorted(all_dates)
            
            values = []
            for date in sorted_dates:
                daily_value = 0
                for stock in self.filtered_portfolio:
                    symbol = stock['sembol']
                    price = all_data[symbol].get(date, stock.get('guncel_fiyat', stock['ort_maliyet']))
                    daily_value += stock['adet'] * price
                values.append(daily_value)
            
            total_cost = sum(s['adet'] * s['ort_maliyet'] for s in self.filtered_portfolio)
            
            return sorted_dates, values, total_cost
            
        except Exception as e:
            print(f"Portföy geçmişi hatası: {e}")
            return self._generate_simulated_history(days)
    
    def _generate_simulated_history(self, days: int) -> Tuple[List[datetime], List[float], float]:
        """Simüle geçmiş"""
        dates = [datetime.now() - timedelta(days=days-i) for i in range(days)]
        total_cost = sum(s['adet'] * s['ort_maliyet'] for s in self.filtered_portfolio) if self.filtered_portfolio else 10000
        current = sum(s['adet'] * s.get('guncel_fiyat', s['ort_maliyet']) for s in self.filtered_portfolio) if self.filtered_portfolio else 10000
        
        np.random.seed(42)
        values = []
        for i in range(days):
            progress = i / (days - 1) if days > 1 else 1
            base_value = total_cost + (current - total_cost) * progress
            noise = base_value * np.random.uniform(-0.02, 0.02)
            values.append(base_value + noise)
        
        return dates, values, total_cost
    
    # ========================================================================
    # RISK TAB - RESPONSIVE
    # ========================================================================
    
    def _create_risk_tab(self) -> None:
        """Risk sekmesi - Büyük containerlar ve tam sığan grafikler"""
        tab = self.tabview.tab(TabName.RISK.value)
        
        # Ana scroll container
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=3, pady=3)
        
        ctk.CTkLabel(
            scroll, 
            text="⚠️ Risk Analizi", 
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=(0, 10))
        
        # Ana container'ların yüksekliğini ana ekrana göre ayarla
        window_height = self.parent.winfo_height()
        matrix_height = int(window_height * 0.45)  # %45 yükseklik
        volatility_height = int(window_height * 0.35)  # %35 yükseklik
        
        # 1. Korelasyon Matrisi için BÜYÜK container - SABIT YÜKSEK BOYUT
        corr_frame = ctk.CTkFrame(
            scroll,
            fg_color=("gray90", "gray13"),
            corner_radius=8,
            height=matrix_height  # Pencereye göre orantılı
        )
        corr_frame.pack(fill="both", expand=True, padx=4, pady=4)
        corr_frame.pack_propagate(False)  # ÖNEMLİ: Boyutu koru!
        
        # 2. Volatilite için BÜYÜK container - SABIT YÜKSEK BOYUT  
        risk_frame = ctk.CTkFrame(
            scroll,
            fg_color=("gray90", "gray13"),
            corner_radius=8,
            height=volatility_height  # Pencereye göre orantılı
        )
        risk_frame.pack(fill="both", expand=True, pady=(10, 4), padx=4)
        risk_frame.pack_propagate(False)  # ÖNEMLİ: Boyutu koru!
        
        # Grafikleri oluştur
        if len(self.portfolio) >= 2:
            self._create_correlation_matrix_fullsize(corr_frame)
        else:
            self._show_empty_message(corr_frame, "Korelasyon için en az 2 hisse gerekli")
        
        self._create_risk_distribution_fullsize(risk_frame)


    def _create_correlation_matrix_fullsize(self, container: ctk.CTkFrame) -> None:
        """Korelasyon matrisi - Container'a tam sığacak versiyon"""
        if not self.api:
            self._show_empty_message(container, "API bağlantısı gerekli")
            return
        
        try:
            # Veri hazırlama
            symbols = [s['sembol'] for s in self.portfolio[:10]]
            
            if len(symbols) < 2:
                self._show_empty_message(container, "En az 2 hisse gerekli")
                return
            
            price_data = {}
            for symbol in symbols:
                historical = self.api.get_historical_data(symbol, 90)
                
                if is_dataframe_valid(historical):
                    price_col = next((col for col in ['HISSE_KAPANIS', 'Close', 'close', 'Kapanış'] 
                                     if col in historical.columns), None)
                    
                    if price_col:
                        price_data[symbol] = historical[price_col].values.tolist()
            
            if len(price_data) < 2:
                self._show_empty_message(container, "Yeterli veri yok")
                return
            
            min_len = min(len(v) for v in price_data.values())
            df = pd.DataFrame({k: v[-min_len:] for k, v in price_data.items()})
            corr = df.pct_change().corr()
            
            # Container boyutlarını al (parent zaten pack_propagate(False) kullanıyor)
            container.update_idletasks()  # Gerçek boyutu güncelle
            width = container.winfo_width()
            height = container.winfo_height()
            
            # Figure oluştur - matplotlib.Figure kullan (plt.figure değil!)
            fig = matplotlib.figure.Figure(figsize=(width/100, height/100), dpi=100)
            
            # Tema ayarları
            if self.theme == "dark":
                fig.patch.set_facecolor('#2b2b2b')
                text_color = 'white'
            else:
                fig.patch.set_facecolor('#f0f0f0')
                text_color = 'black'
            
            # Subplot oluştur ve pozisyonunu ayarla
            ax = fig.add_axes([0.12, 0.15, 0.75, 0.75])  # [left, bottom, width, height]
            
            # Korelasyon matrisi
            im = ax.imshow(corr.values, cmap='RdYlGn', vmin=-1, vmax=1, aspect='auto')
            
            # Tick'ler
            ax.set_xticks(np.arange(len(corr.columns)))
            ax.set_yticks(np.arange(len(corr.columns)))
            
            # Font boyutu - hisse sayısına göre
            font_size = max(8, min(12, int(20/len(corr.columns))))
            
            ax.set_xticklabels(corr.columns, fontsize=font_size, color=text_color, weight='bold')
            ax.set_yticklabels(corr.columns, fontsize=font_size, color=text_color, weight='bold')
            plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
            
            # Değerleri yaz
            for i in range(len(corr.columns)):
                for j in range(len(corr.columns)):
                    value = corr.iloc[i, j]
                    txt_color = 'white' if abs(value) > 0.5 else 'black'
                    ax.text(j, i, f'{value:.2f}', ha="center", va="center",
                           color=txt_color, fontsize=font_size, weight='bold')
            
            # Başlık
            ax.set_title('Hisse Korelasyon Matrisi', fontsize=font_size+4, 
                        fontweight='bold', color=text_color, pad=15)
            
            # Colorbar - manuel pozisyon
            cbar_ax = fig.add_axes([0.88, 0.15, 0.03, 0.75])
            cbar = fig.colorbar(im, cax=cbar_ax)
            cbar.set_label('Korelasyon', fontsize=font_size+1, color=text_color)
            cbar.ax.tick_params(labelsize=font_size, colors=text_color)
            
            # Grid çizgileri
            ax.set_xticks(np.arange(len(corr.columns)+1)-.5, minor=True)
            ax.set_yticks(np.arange(len(corr.columns)+1)-.5, minor=True)
            ax.grid(which="minor", color='gray', linestyle='-', linewidth=0.8, alpha=0.3)
            
            # Canvas - tam container'a sığacak
            canvas = FigureCanvasTkAgg(fig, container)
            canvas.draw()
            canvas_widget = canvas.get_tk_widget()
            canvas_widget.pack(fill="both", expand=True)
            
        except Exception as e:
            print(f"Korelasyon hatası: {e}")
            import traceback
            traceback.print_exc()
            self._show_empty_message(container, "Korelasyon hesaplanamadı")


    def _create_risk_distribution_fullsize(self, container: ctk.CTkFrame) -> None:
        """Risk dağılımı - Container'a tam sığacak versiyon"""
        if not self.filtered_portfolio:
            self._show_empty_message(container, "Portföy boş")
            return
        
        try:
            # Veri hazırlama
            data = []
            for stock in self.filtered_portfolio:
                symbol = stock['sembol']
                if self.api:
                    try:
                        vol = self.api.calculate_volatility(symbol, 30)
                        if not vol or vol <= 0:
                            vol = 25.0
                    except:
                        vol = 25.0
                else:
                    vol = 25.0
                data.append((symbol, vol))
            
            # Sırala ve limitle
            data.sort(key=lambda x: x[1], reverse=True)
            if len(data) > 15:
                data = data[:15]  # Max 15 hisse göster
            
            symbols = [d[0] for d in data]
            volatilities = [d[1] for d in data]
            
            # Container boyutlarını al
            container.update_idletasks()
            width = container.winfo_width()
            height = container.winfo_height()
            
            # Figure oluştur - container boyutlarını kullan
            fig = matplotlib.figure.Figure(figsize=(width/100, height/100), dpi=100)
            
            # Tema ayarları
            if self.theme == "dark":
                fig.patch.set_facecolor('#2b2b2b')
                text_color = 'white'
                grid_color = 'gray'
            else:
                fig.patch.set_facecolor('#f0f0f0')
                text_color = 'black'
                grid_color = '#999999'
            
            # Subplot - pozisyonu manuel ayarla (daha geniş alan)
            ax = fig.add_axes([0.12, 0.15, 0.85, 0.75])  # [left, bottom, width, height]
            
            # Renklendirme
            colors = ['#e74c3c' if v > 40 else '#f39c12' if v > 25 else '#2ecc71' for v in volatilities]
            
            # Barları çiz
            y_pos = np.arange(len(symbols))
            
            # Bar yüksekliği - hisse sayısına göre ayarla
            bar_height = min(0.7, 8.0 / len(symbols))
            
            bars = ax.barh(y_pos, volatilities, color=colors, height=bar_height, 
                          edgecolor='white', linewidth=1)
            
            # Font boyutu - container boyutuna göre
            font_size = max(8, min(11, int(height/50)))
            
            # Y ekseni etiketleri
            ax.set_yticks(y_pos)
            ax.set_yticklabels(symbols, fontsize=font_size, color=text_color, weight='bold')
            ax.invert_yaxis()
            
            # Değer etiketleri
            for bar, vol in zip(bars, volatilities):
                ax.text(vol/2, bar.get_y() + bar.get_height()/2,
                      f'{vol:.1f}%', ha='center', va='center',
                      fontsize=font_size, color='white', weight='bold')
            
            # Başlık
            ax.set_title('Hisse Bazında Risk Dağılımı (Volatilite)', 
                        fontsize=font_size+3, fontweight='bold', 
                        color=text_color, pad=15)
            
            # Risk bölgeleri
            max_vol = max(volatilities) if volatilities else 50
            ax.axvspan(0, 25, alpha=0.1, color='green')
            ax.axvspan(25, 40, alpha=0.1, color='orange')
            ax.axvspan(40, max_vol*1.1, alpha=0.1, color='red')
            
            # X ekseni
            ax.set_xlabel('Volatilite (%)', fontsize=font_size+1, color=text_color)
            ax.set_xlim(0, max_vol*1.1)
            ax.tick_params(axis='x', labelsize=font_size, colors=text_color)
            
            # Grid
            ax.grid(True, axis='x', alpha=0.3, color=grid_color)
            
            # Legend
            from matplotlib.patches import Patch
            legend_elements = [
                Patch(facecolor='#2ecc71', label='Düşük Risk (<25%)'),
                Patch(facecolor='#f39c12', label='Orta Risk (25-40%)'),
                Patch(facecolor='#e74c3c', label='Yüksek Risk (>40%)')
            ]
            ax.legend(handles=legend_elements, loc='upper right', 
                     fontsize=font_size, framealpha=0.9)
            
            # Canvas - tam container'a sığacak
            canvas = FigureCanvasTkAgg(fig, container)
            canvas.draw()
            canvas_widget = canvas.get_tk_widget()
            canvas_widget.pack(fill="both", expand=True)
            
        except Exception as e:
            print(f"Risk dağılımı hatası: {e}")
            import traceback
            traceback.print_exc()
            self._show_empty_message(container, "Grafik oluşturulamadı")
    
    # ========================================================================
    # COMPARISON TAB - RESPONSIVE
    # ========================================================================
    
    def _create_comparison_tab(self) -> None:
        """Karşılaştırma sekmesi - Dinamik"""
        tab = self.tabview.tab(TabName.COMPARISON.value)
        
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=3, pady=3)
        
        ctk.CTkLabel(scroll, text="🔍 Benchmark Karşılaştırması", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(0, 10))
        
        comp_frame = self.chart_manager.create_responsive_frame(
            scroll,
            min_height=300,
            aspect_ratio=2.0
        )
        comp_frame.pack(fill="both", expand=True, pady=6, padx=4)
        self._create_benchmark_comparison(comp_frame)
    
    def _create_benchmark_comparison(self, container: ResponsiveChartFrame) -> None:
        """BIST100 karşılaştırması - Dinamik"""
        period = Period.from_label(self.period_var.get() if self.period_var else "90 Gün")
        days = period.days if period.days > 0 else 90
        
        port_dates, port_values, _ = self._get_portfolio_history(days)
        
        bist_dates, bist_values = [], []
        
        if self.api:
            try:
                bist_data = self.api.get_bist100_data(days)
                
                if is_dataframe_valid(bist_data):
                    price_col = next((col for col in ['HISSE_KAPANIS', 'Close', 'close', 'Kapanış'] if col in bist_data.columns), None)
                    
                    if price_col:
                        if not isinstance(bist_data.index, pd.DatetimeIndex):
                            bist_data.index = pd.to_datetime(bist_data.index)
                        
                        bist_dates = bist_data.index.tolist()
                        bist_values = [safe_float(v) for v in bist_data[price_col].values]
                        
            except Exception as e:
                print(f"BIST100 verisi hatası: {e}")
        
        if not port_values or not bist_values:
            self._show_empty_message(container, "Karşılaştırma verisi bulunamadı")
            return
        
        port_dates, port_values, bist_dates, bist_values = self._align_timeseries(port_dates, port_values, bist_dates, bist_values)
        
        if not port_values or not bist_values:
            self._show_empty_message(container, "Veriler eşleştirilemedi")
            return
        
        port_norm = [v / port_values[0] * 100 for v in port_values] if port_values and port_values[0] > 0 else []
        bist_norm = [v / bist_values[0] * 100 for v in bist_values] if bist_values and bist_values[0] > 0 else []
        
        if not port_norm or not bist_norm:
            self._show_empty_message(container, "Normalize edilemedi")
            return
        
        try:
            fig, ax = self.chart_manager.create_dynamic_figure(container)
            
            ax.plot(port_dates, port_norm, 'b-', linewidth=1.5, label='Portföyüm')
            ax.plot(bist_dates, bist_norm, 'r--', linewidth=1.5, label='BIST100')
            ax.axhline(y=100, color='gray', linestyle='-', linewidth=0.5, alpha=0.5)
            
            # Farkı vurgula
            ax.fill_between(port_dates, port_norm, bist_norm, alpha=0.1,
                           color='green' if port_norm[-1] > bist_norm[-1] else 'red')
            
            ax.set_xlabel('Tarih', fontsize=9)
            ax.set_ylabel('Normalize Değer (100 = Başlangıç)', fontsize=9)
            ax.set_title('Portföy vs BIST100', fontsize=11, fontweight='bold')
            ax.legend(fontsize=8, loc='best')
            ax.grid(True, alpha=0.2)
            ax.tick_params(labelsize=8)
            
            import matplotlib.dates as mdates
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
            ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
            
            # Performance farkı annotation
            diff = port_norm[-1] - bist_norm[-1]
            ax.annotate(f'Fark: {diff:+.1f}%', 
                       xy=(port_dates[-1], port_norm[-1]),
                       xytext=(10, 10), textcoords='offset points',
                       fontsize=9, fontweight='bold',
                       color='green' if diff > 0 else 'red')
            
            fig.tight_layout(pad=0.5)
            self.chart_manager.embed_figure(fig, container)
            
        except Exception as e:
            print(f"Benchmark comparison hatası: {e}")
            self._show_empty_message(container, "Grafik oluşturulamadı")
    
    def _align_timeseries(self, dates1: List[datetime], values1: List[float], dates2: List[datetime], values2: List[float]) -> Tuple[List[datetime], List[float], List[datetime], List[float]]:
        """Zaman serilerini eşleştir"""
        if not dates1 or not dates2 or not values1 or not values2:
            return [], [], [], []
        
        try:
            df1 = pd.DataFrame({'date': dates1, 'value': values1})
            df1['date'] = pd.to_datetime(df1['date'])
            df1.set_index('date', inplace=True)
            
            df2 = pd.DataFrame({'date': dates2, 'value': values2})
            df2['date'] = pd.to_datetime(df2['date'])
            df2.set_index('date', inplace=True)
            
            merged = df1.join(df2, how='inner', lsuffix='_1', rsuffix='_2')
            
            if merged.empty:
                min_len = min(len(dates1), len(dates2))
                return dates1[:min_len], values1[:min_len], dates2[:min_len], values2[:min_len]
            
            aligned_dates = merged.index.tolist()
            aligned_values1 = merged['value_1'].tolist()
            aligned_values2 = merged['value_2'].tolist()
            
            return aligned_dates, aligned_values1, aligned_dates, aligned_values2
            
        except Exception as e:
            print(f"Zaman serisi eşleştirme hatası: {e}")
            min_len = min(len(dates1), len(dates2))
            return dates1[:min_len], values1[:min_len], dates2[:min_len], values2[:min_len]
    
    # ========================================================================
    # DIVIDEND TAB
    # ========================================================================
    
    def _create_dividend_tab(self) -> None:
        """Temettü sekmesi"""
        tab = self.tabview.tab(TabName.DIVIDEND.value)
        
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=3, pady=3)
        
        try:
            dividends = self.db.get_dividends() or []
        except:
            dividends = []
        
        total_div = sum(d.get('tutar', 0) for d in dividends)
        
        summary = ctk.CTkFrame(scroll, corner_radius=10, fg_color=("gray85", "gray17"))
        summary.pack(fill="x", pady=(0, 12), padx=2)
        
        ctk.CTkLabel(summary, text="💰", font=ctk.CTkFont(size=36)).pack(pady=(12, 6))
        ctk.CTkLabel(summary, text="Toplam Temettü Geliri", font=ctk.CTkFont(size=12), text_color="gray").pack()
        ctk.CTkLabel(summary, text=f"{total_div:,.2f} ₺", font=ctk.CTkFont(size=26, weight="bold"), text_color=COLORS["success"]).pack(pady=(3, 6))
        ctk.CTkLabel(summary, text=f"{len(dividends)} ödeme", font=ctk.CTkFont(size=10), text_color="gray").pack(pady=(0, 12))
        
        if dividends:
            # Temettü grafiği
            if len(dividends) >= 2:
                chart_frame = self.chart_manager.create_responsive_frame(
                    scroll,
                    min_height=200,
                    aspect_ratio=2.5
                )
                chart_frame.pack(fill="both", expand=True, pady=8, padx=4)
                self._create_dividend_chart(chart_frame, dividends)
            
            # Liste
            list_frame = ctk.CTkFrame(scroll, corner_radius=10, fg_color=("gray90", "gray13"))
            list_frame.pack(fill="both", expand=True, padx=2)
            
            ctk.CTkLabel(list_frame, text="Temettü Geçmişi", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=10, padx=12, anchor="w")
            
            for div in sorted(dividends, key=lambda x: x.get('tarih', ''), reverse=True)[:10]:
                row = ctk.CTkFrame(list_frame, fg_color=("gray85", "gray17"), corner_radius=6)
                row.pack(fill="x", padx=12, pady=3)
                
                content = ctk.CTkFrame(row, fg_color="transparent")
                content.pack(fill="x", padx=10, pady=6)
                
                ctk.CTkLabel(content, text=div.get('sembol', 'N/A'), font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
                ctk.CTkLabel(content, text=div.get('tarih', 'N/A')[:10], font=ctk.CTkFont(size=9), text_color="gray").pack(side="left", padx=12)
                ctk.CTkLabel(content, text=f"{div.get('tutar', 0):,.2f} ₺", font=ctk.CTkFont(size=12, weight="bold"), text_color=COLORS["success"]).pack(side="right")
        else:
            self._show_empty_message(scroll, "Henüz temettü kaydı yok")
    
    def _create_dividend_chart(self, container: ResponsiveChartFrame, dividends: List[Dict]) -> None:
        """Temettü grafiği - Tema uyumlu yazılar"""
        try:
            # Aylık grupla
            monthly_data = {}
            for div in dividends:
                date_str = div.get('tarih', '')[:7]  # YYYY-MM
                if date_str:
                    if date_str not in monthly_data:
                        monthly_data[date_str] = 0
                    monthly_data[date_str] += div.get('tutar', 0)
            
            if not monthly_data:
                self._show_empty_message(container, "Temettü verisi yok")
                return
            
            sorted_months = sorted(monthly_data.keys())
            values = [monthly_data[m] for m in sorted_months]
            
            fig, ax = self.chart_manager.create_dynamic_figure(container)
            
            # TEMA KONTROLÜ - Text renklerini ayarla
            if self.theme == "dark":
                text_color = 'white'
                value_color = 'white'  # Koyu temada beyaz
                fig.patch.set_facecolor('#2b2b2b')
                ax.set_facecolor('#2b2b2b')
            else:
                text_color = 'black'
                value_color = 'black'  # Açık temada siyah
                fig.patch.set_facecolor('#f0f0f0')
                ax.set_facecolor('#fafafa')
            
            # Barları çiz
            bars = ax.bar(range(len(sorted_months)), values, color=COLORS["success"])
            
            # X ve Y eksenleri
            ax.set_xticks(range(len(sorted_months)))
            ax.set_xticklabels(sorted_months, rotation=45, ha='right', fontsize=8, color=text_color)
            ax.set_ylabel('Temettü (₺)', fontsize=9, color=text_color)
            ax.set_title('Aylık Temettü Gelirleri', fontsize=11, fontweight='bold', color=text_color)
            ax.tick_params(labelsize=8, colors=text_color)
            
            # Eksen çizgileri
            for spine in ax.spines.values():
                spine.set_color(text_color)
                spine.set_alpha(0.3)
            
            # Gridlines
            ax.grid(True, alpha=0.2, color=text_color)
            
            # Değer etiketleri - TEMA UYUMLU
            for bar, value in zip(bars, values):
                ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + max(values)*0.01,
                       f'{value:,.0f}₺', 
                       ha='center', va='bottom', 
                       fontsize=8, 
                       color=value_color,  # Tema uyumlu renk 
                       fontweight='bold')
            
            fig.tight_layout(pad=0.5)
            self.chart_manager.embed_figure(fig, container)
            
        except Exception as e:
            print(f"Temettü grafiği hatası: {e}")
            self._show_empty_message(container, "Grafik oluşturulamadı")
    
    # ========================================================================
    # HELPER METHODS
    # ========================================================================
    
    def _show_empty_message(self, parent, message: str) -> None:
        """Boş mesaj göster"""
        ctk.CTkLabel(
            parent, 
            text=message, 
            text_color="gray", 
            font=ctk.CTkFont(size=11)
        ).pack(expand=True, pady=40)
    
    def _show_error(self, message: str) -> None:
        """Hata mesajı"""
        if self.main_frame:
            for widget in self.main_frame.winfo_children():
                widget.destroy()
        
        ctk.CTkLabel(
            self.main_frame if self.main_frame else self.parent, 
            text=message, 
            text_color=COLORS["danger"]
        ).pack(expand=True, pady=100)
    
    def _safe_calculate(self, func: Callable, default: Any) -> Any:
        """Güvenli hesaplama"""
        try:
            return func()
        except Exception as e:
            print(f"Hesaplama hatası: {e}")
            return default
    
    def _on_filter_change(self) -> None:
        """Filtre değişikliği"""
        self._filter_portfolio()
        self._refresh_current_tab()
    
    def _filter_portfolio(self) -> None:
        """Portföyü filtrele"""
        selected = self.selected_stocks_var.get() if self.selected_stocks_var else "Tümü"
        
        if selected == "Tümü":
            self.filtered_portfolio = self.portfolio.copy()
        else:
            self.filtered_portfolio = [s for s in self.portfolio if s['sembol'] == selected]
        
        if self.filtered_portfolio:
            self.metrics = self.PortfolioMetrics(self.filtered_portfolio, self.transactions, self.api)
    
    def _refresh_current_tab(self) -> None:
        """Mevcut sekmeyi yenile"""
        if not self.tabview:
            return
        
        current = self.tabview.get()
        tab = self.tabview.tab(current)
        
        self.chart_manager.cleanup()
        
        for widget in tab.winfo_children():
            widget.destroy()
        
        tab_map = {
            TabName.GENERAL.value: self._create_general_tab,
            TabName.PERFORMANCE.value: self._create_performance_tab,
            TabName.RISK.value: self._create_risk_tab,
            TabName.COMPARISON.value: self._create_comparison_tab,
            TabName.DIVIDEND.value: self._create_dividend_tab,
        }
        
        if current in tab_map:
            tab_map[current]()
    
    # ========================================================================
    # ACTIONS
    # ========================================================================
    
    def _show_whatif(self) -> None:
        """What-If dialog"""
        try:
            from utils.whatif_dialog import WhatIfDialog
            dialog = WhatIfDialog(self.parent, self.db, self.api, self.portfolio)
            dialog.show()
        except Exception as e:
            print(f"What-If hatası: {e}")
    
    def _export_report(self) -> None:
        """Rapor export"""
        try:
            from utils.export_utils import export_to_txt, export_to_json, export_to_html
            
            dialog = ctk.CTkToplevel(self.parent)
            dialog.title("Rapor Formatı")
            dialog.geometry("400x300")
            dialog.transient(self.parent)
            dialog.grab_set()
            
            x = (dialog.winfo_screenwidth() - 400) // 2
            y = (dialog.winfo_screenheight() - 300) // 2
            dialog.geometry(f"400x300+{x}+{y}")
            
            ctk.CTkLabel(dialog, text="📤 Rapor Dışa Aktar", font=ctk.CTkFont(size=20, weight="bold")).pack(pady=20)
            
            report_data = self._prepare_report_data()
            
            for text, fmt, color in [
                ("📝 Metin (.txt)", "txt", COLORS["primary"]), 
                ("🔡 JSON (.json)", "json", COLORS["purple"]), 
                ("📊 HTML (.html)", "html", COLORS["success"])
            ]:
                ctk.CTkButton(
                    dialog, text=text, fg_color=color, height=40, 
                    command=lambda f=fmt: self._do_export(f, report_data, dialog)
                ).pack(fill="x", padx=30, pady=5)
            
        except ImportError:
            self._simple_export()
    
    def _prepare_report_data(self) -> Dict[str, Any]:
        """Rapor verisi hazırla"""
        data = {"tarih": datetime.now().isoformat(), "portfoy_sayisi": len(self.portfolio)}
        
        if self.metrics:
            data.update({
                "toplam_getiri": self._safe_calculate(self.metrics.calculate_total_return, 0),
                "volatilite": self._safe_calculate(self.metrics.calculate_volatility, 0),
                "max_dusus": self._safe_calculate(self.metrics.calculate_max_drawdown, 0),
                "sharpe_orani": self._safe_calculate(self.metrics.calculate_sharpe_ratio, 0),
                "diversifikasyon": self._safe_calculate(self.metrics.calculate_diversification_score, 0),
            })
            
            try:
                composition = self.metrics.get_portfolio_composition()
                data["portfoy_bilesimi"] = [
                    {"symbol": c.symbol, "weight": c.weight, "value": c.value, "profit_loss": c.profit_loss} 
                    for c in composition
                ]
            except:
                data["portfoy_bilesimi"] = []
        
        return data
    
    def _do_export(self, format_id: str, data: Dict, dialog: ctk.CTkToplevel) -> None:
        """Export işlemi"""
        try:
            from utils.export_utils import export_to_txt, export_to_json, export_to_html
            
            dialog.destroy()
            
            export_funcs = {"txt": export_to_txt, "json": export_to_json, "html": export_to_html}
            export_funcs[format_id](data, title="Portföy Analiz Raporu")
                
        except Exception as e:
            print(f"Export hatası: {e}")
    
    def _simple_export(self) -> None:
        """Basit export"""
        from tkinter import filedialog
        
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt", 
            filetypes=[("Text", "*.txt")], 
            title="Raporu Kaydet"
        )
        
        if not filename:
            return
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("=" * 50 + "\nPORTFÖY ANALİZ RAPORU\n" + "=" * 50 + "\n\n")
                f.write(f"Tarih: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n")
                
                if self.metrics:
                    f.write(f"Toplam Getiri: {self.metrics.calculate_total_return():.2f}%\n")
                    f.write(f"Volatilite: {self.metrics.calculate_volatility():.2f}%\n")
                    f.write(f"Max Düşüş: {self.metrics.calculate_max_drawdown():.2f}%\n")
        except Exception as e:
            print(f"Export hatası: {e}")