#!/usr/bin/env python3
import sys
import os

if sys.platform.startswith("linux"):
    # The embedded Qt WebEngine window is running on X11 here, and Chromium is
    # falling back to Vulkan because GBM is unavailable. That path is prone to
    # flicker and repaint glitches during typing, so force software rendering for
    # the wrapper only.
    os.environ.setdefault(
        "QTWEBENGINE_CHROMIUM_FLAGS",
        "--disable-gpu --disable-gpu-compositing --disable-features=Vulkan"
    )
    os.environ.setdefault("QT_OPENGL", "software")

try:
    from PyQt6.QtCore import QUrl, Qt
    from PyQt6.QtGui import QIcon, QColor
    from PyQt6.QtWidgets import QApplication, QMainWindow
    from PyQt6.QtWebEngineCore import QWebEngineProfile
    from PyQt6.QtWebEngineWidgets import QWebEngineView
except ImportError as e:
    print(f"Error importing PyQt6: {e}")
    sys.exit(1)

ICON_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "frontend",
    "public",
    "icon-512.png",
)

class GuaardvarkWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Guaardvark")
        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))
        self.resize(1280, 800)
        self.setMinimumSize(1024, 768)
        
        # Prevent white flash before page load
        self.setStyleSheet("QMainWindow { background-color: #000000; }")

        self.browser = QWebEngineView()
        self.browser.page().setBackgroundColor(QColor(0, 0, 0))
        
        # Enable localStorage and other necessary web features
        profile = self.browser.page().profile()
        profile.setPersistentStoragePath(os.path.join(os.path.expanduser('~'), '.guaardvark_qt_data'))
        
        self.browser.setUrl(QUrl("http://localhost:5173"))
        
        self.setCentralWidget(self.browser)

def main():
    if sys.platform.startswith("linux"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL, True)
    
    app = QApplication(sys.argv)
    app.setApplicationName("Guaardvark")
    if hasattr(app, "setDesktopFileName"):
        app.setDesktopFileName("Guaardvark")
    if os.path.exists(ICON_PATH):
        app.setWindowIcon(QIcon(ICON_PATH))
    
    window = GuaardvarkWindow()
    window.show()
    
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
