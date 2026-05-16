"""Compatibility entrypoint for local Streamlit runs.

The frontend component lives in `frontend/app.py`. Keeping this wrapper lets
`streamlit run app.py` continue to work during local development.
"""

from frontend.app import *  # noqa: F401,F403
