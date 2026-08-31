"""PyInstaller entry; multiprocessing support must precede CLI dispatch."""
import multiprocessing

from tangerine_photo_assistant.desktop import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
