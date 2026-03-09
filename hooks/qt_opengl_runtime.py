import os

# Prefer stable desktop OpenGL in frozen Windows builds.
# Do not overwrite if the user explicitly set this environment variable.
os.environ.setdefault("QT_OPENGL", "desktop")
