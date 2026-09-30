"""`palissy-serve`: run the API with uvicorn."""

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="palissy-serve")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("palissy.api:create_app", factory=True, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
