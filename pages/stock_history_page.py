# pages/stock_history_page.py

import matplotlib
matplotlib.use('TkAgg')

import customtkinter as ctk
from datetime import datetime, timedelta
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import pandas as pd
from config import COLORS
import threading

# ------------------------------------------------------------------
# AKILLI KÜTÜPHANE YÜKLEYİCİ (HEM ESKİ HEM YENİ SÜRÜM DESTEĞİ)
# ------------------------------------------------------------------
ISYATIRIM_STATUS = "NONE" # NONE, V5 (Yeni), V3 (Eski)

try:
    # Önce en yeni sürümü dene (v5.0.0+)
    from isyatirimhisse import StockData
    ISYATIRIM_STATUS = "V5"
except ImportError:
    try:
        # Olmazsa eski sürümü dene (v3.x - v4.x)
        from isyatirimhisse import fetch_data
        ISYATIRIM_STATUS = "V3"
    except ImportError:
        print("⚠️ 'isyatirimhisse' kütüphanesi tamamen bulunamadı.")
        ISYATIRIM_STATUS = "NONE"
# ------------------------------------------------------------------

class StockHistoryPage:
    def __init__(self, parent, db, api, theme):
        self.parent = parent
        self.db = db
        self.api = api
        self.theme = theme
        
        self.stock_symbol = None
        self.stock_data = None
        self.chart_period = "1y"
        
        # UI Elemanları
        self.stock_selector = None
        self.period_selector = None
        self.tabview = None
        
    def create(self):
        """Ana sayfayı oluştur"""
        self.main_frame = ctk.CTkFrame(self.parent, fg_color="transparent")
        self.main_frame.pack(fill="both", expand=True)
        
        # Kontroller
        self.create_controls()
        
        # Sekmeler
        self.tabview = ctk.CTkTabview(self.main_frame, corner_radius=10)
        self.tabview.pack(fill="both", expand=True, padx=5, pady=(10, 5))
        
        self.tabview.add("📊 Genel Bakış")
        self.tabview.add("📈 Fiyat Grafiği")
        self.tabview.add("⚡ Teknik Analiz")
        self.tabview.add("📑 İstatistikler")
        
        # Hoşgeldin mesajı
        self.show_welcome_message()
        
    def show_welcome_message(self):
        tab = self.tabview.tab("📊 Genel Bakış")
        
        message_frame = ctk.CTkFrame(tab, fg_color="transparent")
        message_frame.pack(expand=True)
        
        ctk.CTkLabel(message_frame, text="📈", 
                    font=ctk.CTkFont(size=64)).pack(pady=(50, 20))
        
        ctk.CTkLabel(message_frame, text="Hisse Geçmişi Analizi", 
                    font=ctk.CTkFont(size=24, weight="bold")).pack(pady=10)
        
        status_msg = "İş Yatırım Modülü: "
        if ISYATIRIM_STATUS == "V5": status_msg += "✅ Aktif (Yeni Sürüm)"
        elif ISYATIRIM_STATUS == "V3": status_msg += "✅ Aktif (Eski Sürüm)"
        else: status_msg += "❌ Yüklü Değil"
            
        ctk.CTkLabel(message_frame, text=status_msg, font=ctk.CTkFont(size=12), text_color="gray").pack(pady=5)
        
        ctk.CTkLabel(message_frame, text="👆 Lütfen yukarıdan incelemek istediğiniz hisseyi seçin", 
                    font=ctk.CTkFont(size=14), text_color="gray").pack(pady=5)
        
    def create_controls(self):
        controls_frame = ctk.CTkFrame(self.main_frame, fg_color=("gray85", "gray17"), corner_radius=10)
        controls_frame.pack(fill="x", padx=5, pady=5)
        
        content = ctk.CTkFrame(controls_frame, fg_color="transparent")
        content.pack(fill="x", padx=15, pady=10)
        
        ctk.CTkLabel(content, text="📈 Hisse Geçmişi", 
                   font=ctk.CTkFont(size=20, weight="bold")).pack(side="left")
        
        # Hisse Seçici
        stock_frame = ctk.CTkFrame(content, fg_color="transparent")
        stock_frame.pack(side="left", padx=(20, 0))
        ctk.CTkLabel(stock_frame, text="Hisse:", font=ctk.CTkFont(size=14)).pack(side="left", padx=(0, 5))
        
        portfolio = self.db.get_portfolio()
        stock_options = ["Seçiniz..."] + [s['sembol'] for s in portfolio] + ["➕ Diğer Hisse..."]
        
        self.stock_selector = ctk.CTkComboBox(stock_frame, values=stock_options, width=150, command=self.on_stock_selected)
        self.stock_selector.set("Seçiniz...")
        self.stock_selector.pack(side="left")
        
        # Dönem Seçici
        period_frame = ctk.CTkFrame(content, fg_color="transparent")
        period_frame.pack(side="right")
        ctk.CTkLabel(period_frame, text="Dönem:", font=ctk.CTkFont(size=14)).pack(side="left", padx=(0, 5))
        
        self.period_selector = ctk.CTkComboBox(
            period_frame, 
            values=["1 Ay", "3 Ay", "6 Ay", "1 Yıl", "5 Yıl"],
            width=100,
            command=self.on_period_selected
        )
        self.period_selector.set("1 Yıl")
        self.period_selector.pack(side="left")
    
    def on_stock_selected(self, symbol):
        if symbol == "Seçiniz...": return
        if symbol == "➕ Diğer Hisse...":
            self.show_custom_stock_dialog()
            return
        self.stock_symbol = symbol
        self.load_stock_data()
    
    def on_period_selected(self, period):
        period_map = {"1 Ay": "1mo", "3 Ay": "3mo", "6 Ay": "6mo", "1 Yıl": "1y", "5 Yıl": "5y"}
        self.chart_period = period_map.get(period, "1y")
        if self.stock_symbol: self.load_stock_data()
    
    def show_custom_stock_dialog(self):
        dialog = ctk.CTkToplevel(self.parent)
        dialog.title("Özel Hisse")
        dialog.geometry("300x150")
        dialog.transient(self.parent)
        dialog.grab_set()
        
        ctk.CTkLabel(dialog, text="Hisse Kodu (Örn: THYAO):").pack(pady=10)
        entry = ctk.CTkEntry(dialog)
        entry.pack(pady=5)
        entry.focus()
        
        def submit():
            s = entry.get().upper().strip()
            if s:
                self.stock_symbol = s
                dialog.destroy()
                self.load_stock_data()
        
        ctk.CTkButton(dialog, text="Tamam", command=submit).pack(pady=10)
        entry.bind("<Return>", lambda e: submit())

    def load_stock_data(self):
        if not self.tabview: return
        
        # Loading göster
        for t in ["📊 Genel Bakış", "📈 Fiyat Grafiği", "⚡ Teknik Analiz", "📑 İstatistikler"]:
            try:
                tab = self.tabview.tab(t)
                for w in tab.winfo_children(): w.destroy()
                ctk.CTkLabel(tab, text=f"⏳ {self.stock_symbol} verisi alınıyor...", font=ctk.CTkFont(size=14)).pack(expand=True)
            except: pass
            
        threading.Thread(target=self._load_data_thread, daemon=True).start()

    # ----------------------------------------------------------------------
    # HİBRİT VERİ ÇEKME FONKSİYONU (ÖNEMLİ)
    # ----------------------------------------------------------------------
    def fetch_history_from_isyatirim(self, symbol, period):
        if ISYATIRIM_STATUS == "NONE": return None
        
        try:
            clean_symbol = symbol.replace(".IS", "").upper()
            
            # Tarihleri ayarla
            end_date = datetime.now()
            days_map = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "5y": 1825}
            start_date = end_date - timedelta(days=days_map.get(period, 365))
            
            start_str = start_date.strftime('%d-%m-%Y')
            end_str = end_date.strftime('%d-%m-%Y')
            
            df = None
            
            # DURUMA GÖRE ÇEK
            if ISYATIRIM_STATUS == "V5":
                # Yeni sürüm: StockData class'ı
                stock_data = StockData()
                df = stock_data.get_data(symbols=[clean_symbol], start_date=start_str, end_date=end_str, frequency='1d')
            
            elif ISYATIRIM_STATUS == "V3":
                # Eski sürüm: fetch_data fonksiyonu
                df = fetch_data(symbol=clean_symbol, start_date=start_str, end_date=end_str, frequency='1d')
            
            if df is None or df.empty: return None
            
            # Sütunları İngilizce yap (Grafik için)
            rename_map = {
                'HGDG_TARIH': 'Date', 'HGDG_KAPANIS': 'Close', 'HGDG_ACILIS': 'Open',
                'HGDG_YUKSEK': 'High', 'HGDG_DUSUK': 'Low', 'HGDG_HACIM': 'Volume',
                'DATE': 'Date', 'CLOSING_PRICE': 'Close', 'OPENING_PRICE': 'Open',
                'HIGH_PRICE': 'High', 'LOW_PRICE': 'Low', 'VOLUME': 'Volume'
            }
            df = df.rename(columns=rename_map)
            
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'])
                df.set_index('Date', inplace=True)
            
            # Sayısal çevirim
            for col in ['Open', 'High', 'Low', 'Close']:
                if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
                
            return df.sort_index()

        except Exception as e:
            print(f"İş Yatırım Hatası: {e}")
            return None
    # ----------------------------------------------------------------------

    def _load_data_thread(self):
        try:
            # Info: yfinance (Hata verirse boş geç)
            info = {}
            ticker = None
            try:
                ticker = yf.Ticker(f"{self.stock_symbol}.IS")
                info = ticker.info
            except: pass

            # History: İş Yatırım
            hist = self.fetch_history_from_isyatirim(self.stock_symbol, self.chart_period)
            
            # Fallback: İş Yatırım boşsa yfinance dene
            if hist is None or hist.empty:
                print("⚠️ İş Yatırım verisi yok, yfinance deneniyor...")
                if ticker:
                    hist = ticker.history(period=self.chart_period)
            
            if hist is None or hist.empty:
                raise Exception("Veri bulunamadı. Lütfen internet bağlantınızı kontrol edin.")

            self.calculate_indicators(hist)
            self.parent.after(0, lambda: self.update_ui(ticker, info, hist))
            
        except Exception as e:
            self.parent.after(0, lambda: self.show_error(str(e)))
            
    def calculate_indicators(self, data):
        df = data.copy()
        try:
            if len(df) >= 20: df['SMA20'] = df['Close'].rolling(window=20).mean()
            if len(df) >= 50: df['SMA50'] = df['Close'].rolling(window=50).mean()
            if len(df) >= 200: df['SMA200'] = df['Close'].rolling(window=200).mean()
            
            if len(df) >= 20:
                df['BB_middle'] = df['Close'].rolling(window=20).mean()
                df['BB_std'] = df['Close'].rolling(window=20).std()
                df['BB_upper'] = df['BB_middle'] + 2 * df['BB_std']
                df['BB_lower'] = df['BB_middle'] - 2 * df['BB_std']
            
            if len(df) >= 15:
                delta = df['Close'].diff()
                up = delta.clip(lower=0)
                down = -1 * delta.clip(upper=0)
                ema_up = up.ewm(com=13, adjust=False).mean()
                ema_down = down.ewm(com=13, adjust=False).mean()
                rs = ema_up / ema_down
                df['RSI'] = 100 - (100 / (1 + rs))
            
            if len(df) >= 26:
                exp12 = df['Close'].ewm(span=12, adjust=False).mean()
                exp26 = df['Close'].ewm(span=26, adjust=False).mean()
                df['MACD'] = exp12 - exp26
                df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
                df['MACD_Hist'] = df['MACD'] - df['Signal']
                
            self.stock_data = df
        except: self.stock_data = df

    def update_ui(self, ticker, info, hist):
        if not self.tabview: return
        for t in ["📊 Genel Bakış", "📈 Fiyat Grafiği", "⚡ Teknik Analiz", "📑 İstatistikler"]:
            try:
                tab = self.tabview.tab(t)
                for w in tab.winfo_children(): w.destroy()
            except: pass
            
        try:
            self.create_overview_tab(info, hist)
            self.create_price_chart_tab(hist)
            self.create_technical_tab()
            self.create_stats_tab(hist)
        except Exception as e:
            self.show_error(f"UI Hatası: {str(e)}")

    def create_overview_tab(self, info, hist):
        tab = self.tabview.tab("📊 Genel Bakış")
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        
        # Başlık
        header = ctk.CTkFrame(scroll, fg_color="transparent")
        header.pack(fill="x", pady=10)
        ctk.CTkLabel(header, text=self.stock_symbol, font=ctk.CTkFont(size=32, weight="bold")).pack(side="left")
        lname = info.get('longName', '')
        if lname: ctk.CTkLabel(header, text=lname, font=ctk.CTkFont(size=14), text_color="gray").pack(side="left", padx=10)
        
        # Fiyat Kartı
        card = ctk.CTkFrame(scroll, corner_radius=10, fg_color=("gray90", "gray13"))
        card.pack(fill="x", pady=10)
        
        try:
            curr = hist['Close'].iloc[-1]
            prev = hist['Close'].iloc[-2] if len(hist) > 1 else curr
            chg = curr - prev
            pct = (chg/prev)*100 if prev else 0
            color = COLORS["success"] if chg >= 0 else COLORS["danger"]
            
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=15, pady=15)
            ctk.CTkLabel(row, text="Son Fiyat", text_color="gray").pack(anchor="w")
            
            pr = ctk.CTkFrame(row, fg_color="transparent")
            pr.pack(fill="x", pady=5)
            ctk.CTkLabel(pr, text=f"{curr:.2f} ₺", font=ctk.CTkFont(size=28, weight="bold")).pack(side="left")
            ctk.CTkLabel(pr, text=f"{chg:+.2f} ₺ ({pct:+.2f}%)", font=ctk.CTkFont(size=16, weight="bold"), text_color=color).pack(side="left", padx=15)
            
            # OHLC
            day_f = ctk.CTkFrame(card, fg_color="transparent")
            day_f.pack(fill="x", padx=15, pady=(0,15))
            
            op = hist['Open'].iloc[-1] if 'Open' in hist else 0
            hi = hist['High'].iloc[-1] if 'High' in hist else 0
            lo = hist['Low'].iloc[-1] if 'Low' in hist else 0
            
            vals = [("Açılış", op), ("Yüksek", hi), ("Düşük", lo)]
            for l, v in vals:
                f = ctk.CTkFrame(day_f, fg_color="transparent")
                f.pack(side="left", expand=True)
                ctk.CTkLabel(f, text=l, font=ctk.CTkFont(size=11), text_color="gray").pack()
                ctk.CTkLabel(f, text=f"{v:.2f}", font=ctk.CTkFont(weight="bold")).pack()
                
        except: pass
        
        # Şirket Bilgileri
        if info:
            inf_c = ctk.CTkFrame(scroll, corner_radius=10, fg_color=("gray90", "gray13"))
            inf_c.pack(fill="x", pady=10)
            ctk.CTkLabel(inf_c, text="Şirket Bilgileri", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=15, pady=10)
            
            grid = ctk.CTkFrame(inf_c, fg_color="transparent")
            grid.pack(fill="x", padx=15, pady=10)
            
            items = [
                ("Sektör", info.get('sector', '-')),
                ("Piyasa Değeri", f"{info.get('marketCap', 0):,.0f}" if info.get('marketCap') else '-'),
                ("F/K", f"{info.get('trailingPE', 0):.2f}" if info.get('trailingPE') else '-'),
                ("52H Yüksek", f"{info.get('fiftyTwoWeekHigh', 0):.2f}" if info.get('fiftyTwoWeekHigh') else '-')
            ]
            for i, (l, v) in enumerate(items):
                f = ctk.CTkFrame(grid, fg_color="transparent")
                f.grid(row=i//2, column=i%2, sticky="w", pady=5, padx=10)
                ctk.CTkLabel(f, text=l, font=ctk.CTkFont(size=11), text_color="gray").pack(anchor="w")
                ctk.CTkLabel(f, text=v, font=ctk.CTkFont(weight="bold")).pack(anchor="w")

    def create_price_chart_tab(self, hist):
        tab = self.tabview.tab("📈 Fiyat Grafiği")
        frame = ctk.CTkFrame(tab, fg_color=("gray90", "gray13"), corner_radius=10)
        frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        fig = plt.Figure(figsize=(10, 6), dpi=100)
        ax = fig.add_subplot(111)
        bg = '#2b2b2b' if self.theme == "dark" else '#f8f9fa'
        txt = 'white' if self.theme == "dark" else 'black'
        fig.patch.set_facecolor(bg)
        ax.set_facecolor(bg)
        
        dates = mdates.date2num(hist.index.to_pydatetime())
        ax.plot(dates, hist['Close'], color='#14b8a6', linewidth=2, label='Fiyat')
        
        if 'SMA20' in hist.columns: ax.plot(dates, hist['SMA20'], linestyle='--', alpha=0.7, label='SMA 20')
        if 'SMA50' in hist.columns: ax.plot(dates, hist['SMA50'], linestyle='--', alpha=0.7, label='SMA 50')
        
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
        ax.grid(True, alpha=0.3)
        ax.legend(facecolor=bg, edgecolor=txt, labelcolor=txt)
        ax.tick_params(colors=txt)
        for s in ax.spines.values(): s.set_color(txt)
        fig.tight_layout()
        
        canvas = FigureCanvasTkAgg(fig, frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    def create_technical_tab(self):
        tab = self.tabview.tab("⚡ Teknik Analiz")
        if self.stock_data is None: return
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        
        if 'RSI' in self.stock_data.columns:
            f = ctk.CTkFrame(scroll, corner_radius=10, fg_color=("gray90", "gray13"))
            f.pack(fill="x", pady=10)
            ctk.CTkLabel(f, text="RSI (14)", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=15, pady=5)
            
            fig = plt.Figure(figsize=(10, 2.5), dpi=100)
            ax = fig.add_subplot(111)
            bg = '#2b2b2b' if self.theme == "dark" else '#f8f9fa'
            txt = 'white' if self.theme == "dark" else 'black'
            fig.patch.set_facecolor(bg)
            ax.set_facecolor(bg)
            
            dates = mdates.date2num(self.stock_data.index.to_pydatetime())
            ax.plot(dates, self.stock_data['RSI'], color='purple')
            ax.axhline(70, color='red', linestyle='--'); ax.axhline(30, color='green', linestyle='--')
            ax.set_ylim(0, 100)
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
            ax.tick_params(colors=txt)
            for s in ax.spines.values(): s.set_color(txt)
            fig.tight_layout()
            
            canvas = FigureCanvasTkAgg(fig, f)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="x", expand=True, padx=10, pady=5)
            
        if 'MACD' in self.stock_data.columns:
            f = ctk.CTkFrame(scroll, corner_radius=10, fg_color=("gray90", "gray13"))
            f.pack(fill="x", pady=10)
            ctk.CTkLabel(f, text="MACD", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=15, pady=5)
            
            fig = plt.Figure(figsize=(10, 2.5), dpi=100)
            ax = fig.add_subplot(111)
            fig.patch.set_facecolor(bg); ax.set_facecolor(bg)
            
            dates = mdates.date2num(self.stock_data.index.to_pydatetime())
            ax.plot(dates, self.stock_data['MACD'], label='MACD')
            ax.plot(dates, self.stock_data['Signal'], label='Signal')
            ax.bar(dates, self.stock_data['MACD_Hist'], alpha=0.3)
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m'))
            ax.tick_params(colors=txt)
            for s in ax.spines.values(): s.set_color(txt)
            fig.tight_layout()
            
            canvas = FigureCanvasTkAgg(fig, f)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="x", expand=True, padx=10, pady=5)

    def create_stats_tab(self, hist):
        tab = self.tabview.tab("📑 İstatistikler")
        f = ctk.CTkFrame(tab, fg_color=("gray90", "gray13"), corner_radius=10)
        f.pack(fill="x", padx=20, pady=20)
        
        grid = ctk.CTkFrame(f, fg_color="transparent")
        grid.pack(fill="x", padx=20, pady=20)
        for i in range(2): grid.grid_columnconfigure(i, weight=1)
        
        items = [
            ("Ortalama", f"{hist['Close'].mean():.2f}"),
            ("En Yüksek", f"{hist['Close'].max():.2f}"),
            ("En Düşük", f"{hist['Close'].min():.2f}"),
            ("Std Sapma", f"{hist['Close'].std():.2f}")
        ]
        
        for i, (l, v) in enumerate(items):
            c = ctk.CTkFrame(grid, fg_color="transparent")
            c.grid(row=i//2, column=i%2, sticky="w", pady=10, padx=20)
            ctk.CTkLabel(c, text=l, text_color="gray").pack(anchor="w")
            ctk.CTkLabel(c, text=v, font=ctk.CTkFont(weight="bold")).pack(anchor="w")

    def show_error(self, msg):
        if not self.tabview: return
        for t in ["📊 Genel Bakış", "📈 Fiyat Grafiği", "⚡ Teknik Analiz", "📑 İstatistikler"]:
            try:
                tab = self.tabview.tab(t)
                for w in tab.winfo_children(): w.destroy()
                ctk.CTkLabel(tab, text=f"⚠️ {msg}", text_color=COLORS["danger"]).pack(expand=True)
            except: pass