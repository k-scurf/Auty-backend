# Legacy Tkinter UI

The desktop Tkinter application previously lived in `main.py`. It is archived as `main_tk.py` for reference only.

**Default entry point:** `python main.py` starts the FastAPI server and React dashboard.

To run the old UI (not maintained):

```bash
python legacy/tk/main_tk.py
```

Note: `legacy/tk/main_tk.py` still imports root modules (`recognition`, `tracking`, etc.) — run from the repository root.
