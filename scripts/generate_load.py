import argparse
import concurrent.futures
import time
import urllib.request


def send_request(url, timeout):
    start = time.perf_counter()

    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            response.read()

        return True, time.perf_counter() - start

    except Exception:
        return False, time.perf_counter() - start


def main():
    parser = argparse.ArgumentParser(
        description="Generate reproducible HTTP workload."
    )

    parser.add_argument(
        "--url",
        required=True,
        help="Target URL through the Application Load Balancer.",
    )

    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Test duration in seconds.",
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=20,
        help="Number of concurrent workers.",
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=10,
        help="HTTP request timeout.",
    )

    args = parser.parse_args()

    print("Starting workload")
    print(f"URL:      {args.url}")
    print(f"Duration: {args.duration}s")
    print(f"Workers:  {args.workers}")
    print()

    deadline = time.time() + args.duration

    total = 0
    successful = 0
    failed = 0
    latencies = []

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=args.workers
    ) as executor:

        futures = set()

        while time.time() < deadline:

            while (
                len(futures) < args.workers
                and time.time() < deadline
            ):
                futures.add(
                    executor.submit(
                        send_request,
                        args.url,
                        args.timeout,
                    )
                )

            done, futures = concurrent.futures.wait(
                futures,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )

            for future in done:
                success, latency = future.result()

                total += 1
                latencies.append(latency)

                if success:
                    successful += 1
                else:
                    failed += 1

    average_latency = (
        sum(latencies) / len(latencies)
        if latencies
        else 0
    )

    success_rate = (
        successful / total * 100
        if total
        else 0
    )

    print("\nWorkload completed")
    print(f"Total requests:      {total}")
    print(f"Successful requests: {successful}")
    print(f"Failed requests:     {failed}")
    print(f"Success rate:        {success_rate:.2f}%")
    print(f"Average latency:     {average_latency:.4f}s")


if __name__ == "__main__":
    main()
