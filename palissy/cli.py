"""Milestone 1 entry point: question -> search -> hypothesis -> sandbox run -> provenance log."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="palissy")
    parser.add_argument("question", nargs="?", help="Research question")
    parser.parse_args()
    raise SystemExit("Not implemented yet (Milestone 1).")


if __name__ == "__main__":
    main()
