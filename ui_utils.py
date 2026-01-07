"""
UI Utility fonksiyonları - CustomTkinter MessageBox
Güvenli ve hatasız mesaj kutuları
"""

import customtkinter as ctk
from typing import Optional


class CustomMessagebox(ctk.CTkToplevel):
    """Özel mesaj kutusu - Thread-safe ve hatasız"""
    
    def __init__(self, title="Bildirim", message="Mesaj", icon="info", option_type="ok"):
        """
        Args:
            title: Pencere başlığı
            message: Gösterilecek mesaj
            icon: "info", "warning", "error", "question"
            option_type: "ok", "yesno", "okcancel"
        """
        super().__init__()
        
        # Değişkenleri önce ata
        self._message = message
        self._icon = icon
        self._option_type = option_type
        self._result = None
        
        # Pencere ayarları
        self.title(title)
        self.resizable(False, False)
        
        # Üstte tut
        self.lift()
        self.attributes("-topmost", True)
        
        # Widget'ları oluştur
        self._create_widgets()
        
        # Pencereyi ortala
        self._center_window()
        
        # ESC tuşu ile kapat - İLK ÖNCE PROTOCOL AYARLA
        self.protocol("WM_DELETE_WINDOW", self._on_escape)
        self.bind("<Escape>", self._on_escape)
        
        # Grab set (en son yap)
        try:
            self.grab_set()
        except Exception as e:
            print(f"⚠️ Grab set hatası: {e}")
    
    def _create_widgets(self):
        """Widget'ları oluştur"""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # Ana frame
        main_frame = ctk.CTkFrame(self, corner_radius=15)
        main_frame.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        main_frame.grid_columnconfigure(1, weight=1)
        
        # Icon mapping
        icon_map = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "question": "❓",
            "success": "✅"
        }
        
        # Icon
        icon_text = icon_map.get(self._icon, "•")
        icon_label = ctk.CTkLabel(
            main_frame,
            text=icon_text,
            font=ctk.CTkFont(size=48)
        )
        icon_label.grid(row=0, column=0, rowspan=2, padx=20, pady=20)
        
        # Mesaj
        message_label = ctk.CTkLabel(
            main_frame,
            text=self._message,
            font=ctk.CTkFont(size=14),
            wraplength=400,
            justify="left"
        )
        message_label.grid(row=0, column=1, columnspan=2, padx=20, pady=20, sticky="ew")
        
        # Buton frame
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.grid(row=1, column=1, columnspan=2, padx=20, pady=(0, 20), sticky="e")
        
        # Butonları oluştur
        self._create_buttons(button_frame)
    
    def _create_buttons(self, parent):
        """Butonları oluştur"""
        if self._option_type == "ok":
            ok_button = ctk.CTkButton(
                parent,
                text="Tamam",
                command=self._ok_event,
                width=100,
                height=35
            )
            ok_button.pack(padx=5)
            
            # Klavye kısayolları (sadece Return, ESC zaten var)
            self.bind("<Return>", self._ok_event)
            
            # Focus
            ok_button.focus_set()
        
        elif self._option_type == "yesno":
            yes_button = ctk.CTkButton(
                parent,
                text="Evet",
                command=self._yes_event,
                width=100,
                height=35
            )
            yes_button.pack(side="left", padx=5)
            
            no_button = ctk.CTkButton(
                parent,
                text="Hayır",
                command=self._no_event,
                width=100,
                height=35,
                fg_color="#E53935",
                hover_color="#C62828"
            )
            no_button.pack(side="left", padx=5)
            
            # Klavye kısayolları
            self.bind("<Return>", self._yes_event)
            # ESC için _no_event kullanılacak (_on_escape'te)
            
            # Focus
            yes_button.focus_set()
        
        elif self._option_type == "okcancel":
            ok_button = ctk.CTkButton(
                parent,
                text="Tamam",
                command=self._ok_event,
                width=100,
                height=35
            )
            ok_button.pack(side="left", padx=5)
            
            cancel_button = ctk.CTkButton(
                parent,
                text="İptal",
                command=self._cancel_event,
                width=100,
                height=35,
                fg_color=("gray60", "gray40")
            )
            cancel_button.pack(side="left", padx=5)
            
            # Klavye kısayolları
            self.bind("<Return>", self._ok_event)
            # ESC için _cancel_event kullanılacak (_on_escape'te)
            
            # Focus
            ok_button.focus_set()
    
    # ↓↓↓ EKSİK OLAN METOD - BURAYA EKLE ↓↓↓
    def _on_escape(self, event=None):
        """ESC tuşu veya X butonuyla kapatma"""
        if self._option_type == "ok":
            self._ok_event()
        elif self._option_type == "yesno":
            self._no_event()  # ESC = Hayır
        elif self._option_type == "okcancel":
            self._cancel_event()  # ESC = İptal
        else:
            self._ok_event()  # Varsayılan
    
    def _ok_event(self, event=None):
        """Tamam olayı"""
        self._result = True
        self._close()
    
    def _yes_event(self, event=None):
        """Evet olayı"""
        self._result = True
        self._close()
    
    def _no_event(self, event=None):
        """Hayır olayı"""
        self._result = False
        self._close()
    
    def _cancel_event(self, event=None):
        """İptal olayı"""
        self._result = False
        self._close()
    
    def _close(self):
        """Pencereyi güvenli şekilde kapat"""
        try:
            self.grab_release()
        except:
            pass
        
        try:
            self.destroy()
        except:
            pass
    
    def _center_window(self):
        """Pencereyi ekranın ortasında konumlandır"""
        self.update_idletasks()
        
        # Pencere boyutları
        width = self.winfo_width()
        height = self.winfo_height()
        
        # Ekran boyutları
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        
        # Orta pozisyon
        x = (screen_width // 2) - (width // 2)
        y = (screen_height // 2) - (height // 2)
        
        self.geometry(f"+{x}+{y}")
    
    def get(self):
        """Sonucu al (blocking)"""
        try:
            self.master.wait_window(self)
        except Exception as e:
            print(f"⚠️ wait_window hatası: {e}")
        
        return self._result


# ============= PUBLIC FUNCTIONS =============

def showinfo(title: str, message: str) -> Optional[bool]:
    """
    Bilgi mesajı göster
    
    Args:
        title: Başlık
        message: Mesaj
    
    Returns:
        True (her zaman)
    """
    try:
        msg = CustomMessagebox(title, message, icon="info", option_type="ok")
        return msg.get()
    except Exception as e:
        print(f"❌ showinfo hatası: {e}")
        # Fallback: konsola yazdır
        print(f"INFO: {title} - {message}")
        return True


def showerror(title: str, message: str) -> Optional[bool]:
    """
    Hata mesajı göster
    
    Args:
        title: Başlık
        message: Mesaj
    
    Returns:
        True (her zaman)
    """
    try:
        msg = CustomMessagebox(title, message, icon="error", option_type="ok")
        return msg.get()
    except Exception as e:
        print(f"❌ showerror hatası: {e}")
        print(f"ERROR: {title} - {message}")
        return True


def showwarning(title: str, message: str) -> Optional[bool]:
    """
    Uyarı mesajı göster
    
    Args:
        title: Başlık
        message: Mesaj
    
    Returns:
        True (her zaman)
    """
    try:
        msg = CustomMessagebox(title, message, icon="warning", option_type="ok")
        return msg.get()
    except Exception as e:
        print(f"❌ showwarning hatası: {e}")
        print(f"WARNING: {title} - {message}")
        return True


def askyesno(title: str, message: str) -> bool:
    """
    Evet/Hayır sorusu sor
    
    Args:
        title: Başlık
        message: Mesaj
    
    Returns:
        True: Evet seçildi
        False: Hayır seçildi
    """
    try:
        msg = CustomMessagebox(title, message, icon="question", option_type="yesno")
        result = msg.get()
        return result if result is not None else False
    except Exception as e:
        print(f"❌ askyesno hatası: {e}")
        print(f"QUESTION: {title} - {message}")
        return False


def askokcancel(title: str, message: str) -> bool:
    """
    Tamam/İptal sorusu sor
    
    Args:
        title: Başlık
        message: Mesaj
    
    Returns:
        True: Tamam seçildi
        False: İptal seçildi
    """
    try:
        msg = CustomMessagebox(title, message, icon="question", option_type="okcancel")
        result = msg.get()
        return result if result is not None else False
    except Exception as e:
        print(f"❌ askokcancel hatası: {e}")
        print(f"QUESTION: {title} - {message}")
        return False


# ============= EKLEME: Success Mesajı =============

def showsuccess(title: str, message: str) -> Optional[bool]:
    """
    Başarı mesajı göster
    
    Args:
        title: Başlık
        message: Mesaj
    
    Returns:
        True (her zaman)
    """
    try:
        msg = CustomMessagebox(title, message, icon="success", option_type="ok")
        return msg.get()
    except Exception as e:
        print(f"❌ showsuccess hatası: {e}")
        print(f"SUCCESS: {title} - {message}")
        return True


# ============= TEST =============

if __name__ == "__main__":
    """Test fonksiyonları"""
    
    # Test window
    root = ctk.CTk()
    root.title("MessageBox Test")
    root.geometry("400x300")
    
    def test_info():
        result = showinfo("Bilgi", "Bu bir bilgi mesajıdır.")
        print(f"Info sonuç: {result}")
    
    def test_error():
        result = showerror("Hata", "Bu bir hata mesajıdır!")
        print(f"Error sonuç: {result}")
    
    def test_warning():
        result = showwarning("Uyarı", "Bu bir uyarı mesajıdır.")
        print(f"Warning sonuç: {result}")
    
    def test_yesno():
        result = askyesno("Soru", "Devam etmek istiyor musunuz?")
        print(f"YesNo sonuç: {result}")
    
    def test_okcancel():
        result = askokcancel("Onay", "Bu işlemi yapmak istediğinizden emin misiniz?")
        print(f"OkCancel sonuç: {result}")
    
    def test_success():
        result = showsuccess("Başarılı", "İşlem başarıyla tamamlandı!")
        print(f"Success sonuç: {result}")
    
    # Test butonları
    ctk.CTkButton(root, text="Info Test", command=test_info).pack(pady=5)
    ctk.CTkButton(root, text="Error Test", command=test_error).pack(pady=5)
    ctk.CTkButton(root, text="Warning Test", command=test_warning).pack(pady=5)
    ctk.CTkButton(root, text="YesNo Test", command=test_yesno).pack(pady=5)
    ctk.CTkButton(root, text="OkCancel Test", command=test_okcancel).pack(pady=5)
    ctk.CTkButton(root, text="Success Test", command=test_success).pack(pady=5)
    
    root.mainloop()