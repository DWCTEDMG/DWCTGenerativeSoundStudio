from __future__ import annotations

if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    from edmg_studio_backend.cli import main

    main()
