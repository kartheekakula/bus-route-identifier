"""
app.py
======
Standard entry point for Hugging Face Spaces.
Runs the DrishtiCap / Bus Route Identifier Flask application.
"""
import os
from web_app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    app.run(host="0.0.0.0", port=port, debug=False)
