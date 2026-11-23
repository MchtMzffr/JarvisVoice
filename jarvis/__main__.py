"""Start the Windows desktop application or an explicit developer mode."""
import argparse
import sys

from .desktop import DesktopError, report_error, run_browser, run_desktop


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="UI/protocol test; no speech models")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--desktop", action="store_true", help="Windows desktop window")
    mode.add_argument("--browser", action="store_true", help="Explicit system browser mode")
    mode.add_argument("--no-browser", action="store_true", help="Headless local server; no launch token is printed")
    args = parser.parse_args(argv)
    use_desktop = args.desktop or (sys.platform == "win32" and not args.browser and not args.no_browser)
    try:
        if use_desktop:
            run_desktop(demo=args.demo)
        else:
            run_browser(demo=args.demo, no_browser=args.no_browser)
        return 0
    except KeyboardInterrupt:
        return 0
    except DesktopError as exc:
        report_error(str(exc))
        return 1
    except Exception:
        report_error("Jarvis başlatılamadı. KUR.cmd ile kurulum kontrolünü yeniden çalıştır.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
