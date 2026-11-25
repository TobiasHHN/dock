"""Worker-Prozess (Hello World). Echte Jobs (procrastinate) kommen mit Task 5.1."""
import asyncio


async def main() -> None:
    print("worker: bereit (noch keine Jobs)", flush=True)
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
