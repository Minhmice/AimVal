import customtkinter as ctk
import cv2
from gui import ViewerApp

if __name__ == "__main__":
    ctk.set_appearance_mode("Dark")
    app = ViewerApp()
    app.protocol("WM_DELETE_WINDOW", app._on_close)
    app.mainloop()
