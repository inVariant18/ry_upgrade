# Based on RY5088 Monsgeek M1V5 TMR (v408) ry_upgrade.exe

 - `ry_upgrade.exe` used in documentation is from Monsgeek M1V5 TMR `ID_2949_RY5088_AKKO_M1V5 TMR_RY1033_ARGB_KB_V408`
 - `ry_upgrade.exe` from Core68HE uses exactly the same logic.
 - `x1` used for testing and documentation is from Core68HE `ID_3513_RY5088_ML_Core68HE_1M_8K_ARGB_RY1049ES_KB_V504L`

## Summary

The `x1` file is not directly the final firmware image.

Instead, the updater performs these steps:

1. Loads the `x1` file from disk.
2. Rejects empty or trivially small files.
3. Rebuilds a new stream by:
   - keeping byte `0`
   - skipping bytes `1..0xCA`
   - copying bytes from `0xCB` onward
4. Inflates the rebuilt stream as raw deflate.
5. Returns the fully decoded blob.
6. The actual flashed firmware is a sub-region inside that decoded blob.

For the sample analyzed during this work, the decoded container layout was:

| Region | Offset | Size | Meaning |
|---|---:|---:|---|
| Prefix | `0x0000` | `0x5000` (`20480`) | Separate boot/IAP-style image plus padding (bootloader) |
| Firmware payload | `0x5000` | `114420` | Exact match to firmware captured using [DUMMY USB method](https://github.com/echtzeit-solutions/monsgeek-akko-linux/blob/f16083ae12550e64ddbd55689ac38a92da3d9e04/scripts/uhid_dummy_device.py) |
| Suffix | `0x20EF4` | `0x2BC` (`700`) | Structured descriptor/config-like data |

## Main Functions

These are the important functions in the newer `ry_upgrade.exe` build.

| Address | Name (renamed) | Role |
|---|---|---|
| `0x005f2b50` | `FindUpgradeChannelAndLoad` | Chooses the upgrade channel, loads `x1`, and dispatches to the decoder |
| `0x005f1f90` | `RemoveWrapper` | Reads the file, removes the custom wrapper, and prepares the wrapped stream |
| `0x0061ba00` | `InflateFUN` | Streaming inflate driver that expands the rebuilt stream |
| `0x0066fd90` | `FUN_0066fd90` | Low-level deflate/inflate step; references `corrupt deflate stream` |
| `0x00b73200` | `FUN_00b73200` | File read helper used by `RemoveWrapper` |
| `0x005ec920` | `FUN_005ec920` | Resource path builder used before selecting channel files |

## Finding the decoder in Ghidra

The newer build did not expose a normal automatic code xref to the merged `x1x2` string, so the path to the decoder was reconstructed in stages.

### Stage 1: Find the merged channel string

The important string is:

- Address: `0x015c1b88`
- Value:
  `Unable to find the upgrade channel for the current devicex4x5x6x7x3RFx1x2`

This is useful because it contains the `x1x2` marker and identifies the function that selects the update binary.

### Stage 2: Recover the code reference manually

Automatic xrefs were not present in this build, so the string address bytes were searched directly:

- Little-endian bytes for `0x015c1b88`:
  `88 1B 5C 01`
- Matching code location:
  `0x005f2baf`

Inspecting upward from that instruction shows a normal function prologue at `0x005f2b50`, so a function was created there manually and renamed:

- `0x005f2b50` -> `FindUpgradeChannelAndLoad`

### Stage 3: Follow the call to the decoder

Decompiling `FindUpgradeChannelAndLoad` shows the relevant branch for the normal USB path:

- It selects `"x1x2"`
- Loads the associated file contents
- Calls:
  `0x005f1f90`

That function was later renamed:

- `0x005f1f90` -> `RemoveWrapper`

### Stage 4: Follow the inflate path

Inside `RemoveWrapper`, the rebuilt stream is passed to:

- `0x0061ba00` -> `InflateFUN`

Inside `InflateFUN`, the low-level decompression step is:

- `0x0066fd90` -> `FUN_0066fd90`

That low-level function references the string:

- `0x015c7280` -> `corrupt deflate stream`

This confirms the path is raw-deflate based.

## `FindUpgradeChannelAndLoad` at `0x005f2b50`

This function is the outer dispatcher for the update package.

### What it does

- Builds or resolves the path to the channel resource set
- Chooses the correct update channel based on device type
- Uses channel names like:
  - `"x1x2"`
  - `"x2"`
  - `"x3RFx1x2"`
  - `"x4x5x6x7x3RFx1x2"`
  - and related variants
- Loads the selected file contents
- Passes the loaded buffer into `RemoveWrapper`

### Why it matters

This is the function that tells us:

- the updater uses `x1x2` in the normal path
- `x1` is not handled in isolation at first
- the decoder entry point is `RemoveWrapper`

### Important evidence

In the decompilation, the `"x1x2"` branch ends by calling:

- `RemoveWrapper(&sStack_6c);`

This is the handoff into the wrapper-removal logic.

## `RemoveWrapper` at `0x005f1f90`

This is the most important function in the entire `x1` decoding chain.

### What it does, step by step

1. Reads the selected `x1` file from disk.
2. Handles file-read errors.
3. Rejects empty files.
4. Rejects very small files.
5. Allocates a new output vector for a rebuilt stream.
6. Copies the first byte of the original file into the rebuilt vector.
7. Skips `0xCB` bytes from the original file.
8. Copies the remainder of the file after that skip.
9. Copies the rebuilt vector into a stable owned buffer.
10. Allocates inflate scratch/state.
11. Calls the deflate inflater.
12. Returns the decoded blob through `outDecodedResult`.
13. Frees temporary resources.

### Detailed behavior by branch

#### File read

The file-read helper is called here:

- Instruction: `0x005f1ffe`
- Helper: `FUN_00b73200`

This helper fills a result-like structure that encodes:

- success or failure
- loaded file pointer
- loaded file length

#### Error path: file read failed

If the file helper returns an error-tagged object, `RemoveWrapper`:

- constructs an error object
- stores it in the output result
- frees temporary objects
- returns early

#### Empty-file path

If the length is zero, `RemoveWrapper` creates an error state indicating the current upgrade file is empty.

#### Small-file path

If the loaded file is smaller than `0x194`, `RemoveWrapper` also returns an error.

This is a guard that prevents clearly invalid inputs from reaching the inflate code.

### Wrapper-removal core

The wrapper-removal block starts around:

- `0x005f2310` through `0x005f235e`

The key logic is:

1. Allocate a new vector.
2. Append the first byte of the original file.
3. Compute:
   `loaded_len - 0xCB`
4. Copy from:
   `loaded_ptr + 0xCB`
5. Resulting wrapped length becomes:
   `1 + (loaded_len - 0xCB)` which is equal to `loaded_len - 0xCA`

Decompiler comment added at:

- `0x005f2346`

### Equivalent logic in pseudocode

```c
rebuilt[0] = input[0];
memcpy(rebuilt + 1, input + 0xCB, input_len - 0xCB);
wrapped_len = input_len - 0xCA;
```

### Simplified Python equivalent

```python
wrapped = data[:1] + data[0xCB:]
```

### Why this proves a custom wrapper exists

Because the updater does not feed the original file directly into the inflater.

Instead, it explicitly:

- preserves byte `0`
- discards bytes `1..0xCA`
- keeps the rest

That means `x1` contains a custom front wrapper or header block that the actual compressed stream does not use.

### Rebuilt wrapped stream ownership

After rebuilding the wrapped vector, the function copies it into a stable owned allocation:

- this is the buffer later passed to the inflate logic
- this is what the script saves as `x1_wrapped_deflate.bin`

### Inflate call

After building the wrapped stream, `RemoveWrapper` allocates scratch buffers and calls:

- `InflateFUN` at `0x0061ba00`

Decompiler comment added at:

- `0x005f24ce`

## `InflateFUN` at `0x0061ba00`

This function is the streaming inflate driver.

### What it does

- takes the wrapped stream as input
- grows output buffers as needed
- repeatedly calls the lower-level decompression routine
- accumulates the decoded output
- returns status and output buffer information

### Why it matters

This is where the rebuilt stream becomes the fully decoded container.

It does not appear to perform cryptographic decryption.
Instead, it behaves like a normal streaming decompressor.

## `FUN_0066fd90` at `0x0066fd90`

This is the low-level deflate step called by `InflateFUN`.

### Important evidence

The function references:

- `corrupt deflate stream`

The reference chain is:

- string at `0x015c7280`
- xref from `0x0066fede` inside `FUN_0066fd90`

### What this means

This confirms that the updater is inflating deflate-compressed data, not applying AES or another block cipher in this path.

## Exact Decode Rule

The generic decoding rule implemented by the updater is:

```python
wrapped = x1[:1] + x1[0xCB:]
inflated = raw_deflate_inflate(wrapped)
```

## Extraction Script

The helper script created during this work is:

- [extract_x1.py](extract_x1.py)

### What it writes

By default, the script now writes:

- `x1_wrapped_deflate.bin`
- `x1_inflated.bin`
- `x1_assumed_firmware.bin`

### Generic decode

This part is generic and matches the program logic:

```python
wrapped = data[:1] + data[0xCB:]
inflated = zlib.decompressobj(-15).decompress(wrapped)
```

### Default assumed slice

For the analyzed sample, the script also exports an assumed firmware slice using:

- prefix: `0x5000`
- suffix: `0x2BC`

That is:

```python
firmware = inflated[0x5000 : len(inflated) - 0x2BC]
```

Important caveat:

- the wrapper-removal and inflate logic are strongly established as generic
- the final `0x5000` / `0x2BC` slice rule is proven for the analyzed sample, but not yet guaranteed for all keyboard models

## Sample Artifact Sizes

These values came from the analyzed `x1` sample from `ID_3513_RY5088_ML_Core68HE_1M_8K_ARGB_RY1049ES_KB_V504L`

| Artifact | Size |
|---|---:|
| Original `x1` | `55863` |
| Rebuilt wrapped stream | `55661` |
| Inflated decoded container | `135600` |
| Captured firmware (`firmware.bin`) | `114420` |
| Prefix region | `20480` |
| Suffix region | `700` |

## How The Final Firmware Was Proven

The exact flashed firmware was not guessed.
It was proven by comparing the decoded output against a captured, known-good firmware image.

### Result

The captured firmware matches this exact slice:

```text
x1_inflated.bin[0x5000 : 0x5000 + 114420]
```

That match was byte-for-byte exact.

## What The Prefix And Suffix Look Like

Both regions were also analyzed.

### Prefix: first `0x5000` bytes

Observed characteristics:

- starts with a valid Cortex-M vector table
- initial stack pointer looks like:
  `0x20004EB0`
- reset vector encodes an ARM Thumb entry near:
  `0x080002C1`
- contains strings:
  - `" HID IAP Config"` at `0x000010fb`
  - `" HID IAP Interface"` at `0x0000113b`
- ends with a large `FF`-padded region near the `0x5000` boundary

Interpretation:

- this strongly resembles a bootloader or IAP-related firmware region
- it appears to be a self-contained ARM image padded to a neat boundary

### Suffix: final `0x2BC` bytes

Observed characteristics:

- not recognized as code
- no meaningful code xrefs into its start
- contains repeated HID-style item bytes such as:
  - `05`
  - `09`
  - `19`
  - `29`
  - `75`
  - `95`
  - `81`
  - `91`
  - `C0`
- contains `06 FF FF`, which is a classic vendor-defined usage page marker in HID report descriptors

Interpretation:

- this looks like structured descriptor/configuration data
- it may be a continuation of a descriptor table that begins near the end of the main firmware region
- it does not look like encrypted or random trailer data

## Evidence That The Trailer Continues Structured Data

Pattern searches showed HID-style descriptor sequences starting before the firmware/trailer split and continuing into the final `700` bytes.

This means the trailing `0x2BC` region is probably not a completely separate blob.
It is more likely the tail of a larger descriptor/configuration structure within the decoded container.

## What Is Strongly Proven vs What Is Still Assumed

### Strongly proven

- `x1` is loaded and processed through `RemoveWrapper`
- the wrapper-removal rule is:
  `byte0 + bytes[0xCB:]`
- the rebuilt stream is inflated as raw deflate
- the path uses deflate, not AES, in the analyzed code path
- the decoded result is a larger container, not only the final firmware
- for the analyzed sample, the real firmware begins at `0x5000` and matches `firmware.bin`

### Still sample-specific or not yet generalized

- whether all keyboard models use the same `0x5000` prefix length 
- whether all keyboard models use the same `0x2BC` suffix length
- whether every `x1` contains the same style of prefix and trailer layout

## References
 - https://github.com/echtzeit-solutions/monsgeek-akko-linux/
 - Codex to write documentation and python script



---

**Disclaimer: This research is for educational purposes only**