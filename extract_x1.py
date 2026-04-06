from __future__ import annotations

import argparse
import hashlib
import sys
import zlib
from pathlib import Path


HEADER_SKIP = 0xCB
BOOTLOADER_LEN = 0x5000


def decode_x1(data: bytes) -> tuple[bytes, bytes]:
    if len(data) <= HEADER_SKIP:
        raise ValueError(f"x1 is too small: {len(data)} bytes")

    # The updater keeps byte 0, discards bytes 1..0xCA, and inflates the rest as raw deflate.
    wrapped = data[:1] + data[HEADER_SKIP:]
    inflated = zlib.decompressobj(-15).decompress(wrapped)
    return wrapped, inflated


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_int(text: str) -> int:
    return int(text, 0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Decode RY x1 firmware blob")
    parser.add_argument("x1", type=Path, help="Path to resources/x1")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("out"),
        help="Directory to write decoded artifacts into",
    )
    parser.add_argument(
        "--reference",
        type=Path,
        help="Optional captured firmware image to locate inside the inflated blob",
    )
    parser.add_argument(
        "--tail-len",
        type=parse_int,
        help="Optional tail cut length to export for comparison",
    )
    parser.add_argument(
        "--slice-offset",
        type=parse_int,
        help="Optional explicit offset into the inflated blob to export",
    )
    parser.add_argument(
        "--slice-length",
        type=parse_int,
        help="Optional explicit length for --slice-offset",
    )
    args = parser.parse_args()

    x1_path = args.x1
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    data = x1_path.read_bytes()
    wrapped, inflated = decode_x1(data)

    (out_dir / "x1_wrapped_deflate.bin").write_bytes(wrapped)
    (out_dir / "x1_inflated.bin").write_bytes(inflated)

    print(f"x1: {x1_path}")
    print(f"original_size={len(data)}")
    print(f"wrapped_size={len(wrapped)}")
    print(f"inflated_size={len(inflated)}")
    print(f"wrapped_sha256={sha256_hex(wrapped)}")
    print(f"inflated_sha256={sha256_hex(inflated)}")

    if len(inflated) >= BOOTLOADER_LEN:
        bootloader = inflated[:BOOTLOADER_LEN]
        
        # Remove the last 700 bytes for the firmware slice
        suffix_len = 700
        firmware_end = len(inflated) - suffix_len
        firmware = inflated[BOOTLOADER_LEN:firmware_end]
    else:
        bootloader = inflated
        firmware = b""

    (out_dir / "bootloader.bin").write_bytes(bootloader)
    (out_dir / "firmware.bin").write_bytes(firmware)

    print(f"bootloader_size={len(bootloader)}")
    print(f"bootloader_sha256={sha256_hex(bootloader)}")
    print(f"firmware_size={len(firmware)}")
    print(f"firmware_sha256={sha256_hex(firmware)}")

    if args.tail_len is not None:
        if len(inflated) < args.tail_len:
            raise ValueError(
                f"inflated output is only {len(inflated)} bytes; tail_len={args.tail_len} is too large"
            )
        tail = inflated[-args.tail_len :]
        (out_dir / "x1_tail_guess.bin").write_bytes(tail)
        print(
            f"tail_guess_offset={len(inflated) - args.tail_len} "
            f"(0x{len(inflated) - args.tail_len:X})"
        )
        print(f"tail_guess_size={len(tail)}")
        print(f"tail_guess_sha256={sha256_hex(tail)}")

    if (args.slice_offset is None) != (args.slice_length is None):
        raise ValueError("--slice-offset and --slice-length must be provided together")

    if args.slice_offset is not None and args.slice_length is not None:
        if args.slice_offset < 0 or args.slice_length < 0:
            raise ValueError("slice offset and length must be non-negative")
        end = args.slice_offset + args.slice_length
        if end > len(inflated):
            raise ValueError(
                f"slice [0x{args.slice_offset:X}, 0x{end:X}) exceeds inflated size {len(inflated)}"
            )
        sliced = inflated[args.slice_offset:end]
        (out_dir / "x1_explicit_slice.bin").write_bytes(sliced)
        print(f"slice_offset={args.slice_offset} (0x{args.slice_offset:X})")
        print(f"slice_length={args.slice_length}")
        print(f"slice_sha256={sha256_hex(sliced)}")

    if args.reference:
        reference = args.reference.read_bytes()
        offset = inflated.find(reference)
        if offset < 0:
            raise ValueError(
                f"reference image {args.reference} ({len(reference)} bytes) "
                "was not found inside the inflated blob"
            )
        match = inflated[offset : offset + len(reference)]
        (out_dir / "x1_reference_match.bin").write_bytes(match)
        print(f"reference_path={args.reference}")
        print(f"reference_offset={offset} (0x{offset:X})")
        print(f"reference_size={len(reference)}")
        print(f"reference_prefix_len={offset}")
        print(f"reference_suffix_len={len(inflated) - (offset + len(reference))}")
        print(f"reference_sha256={sha256_hex(reference)}")
        print(f"reference_match_sha256={sha256_hex(match)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
