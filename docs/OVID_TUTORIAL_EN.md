<a id="top"></a>

<p align="center">
  <a href="OVID_TUTORIAL.md">中文</a> · <strong>English</strong>
</p>

# 🎬 Creating an OVID File

[← Back to the project README](../README_EN.md)

> [!NOTE]
> This is the preserved optional advanced workflow. Most users can download [OVID Converter v1.3.0-beta.2](https://github.com/akasa828/SD_Card_OVID_Player/releases/tag/v1.3.0-beta.2) and convert an image, image folder, GIF, or video directly into an OVID `.BIN`. The original instructions below remain unchanged for users who want to inspect and control each intermediate step.

> The steps below use `Bad Apple.mp4` as an example.

Putting an MP4 decoder directly on an `F103C8T6` is neither practical nor a good fit for the chip, so the preparation takes a few steps. Still, getting the video to play at all is already pretty satisfying.

```text
Image frames → monochrome BMP → one Img2Lcd .c file per frame → merged .h → OVID .BIN
```

Two Python scripts from this repository are used in the process. [`tools/merge_img2lcd.py`](../tools/merge_img2lcd.py) combines the series of `.c` files generated from the video frames into one `.h` file, while [`tools/h2bin.py`](../tools/h2bin.py) creates and validates the OVID binary. The main workflow below only uses the Python standard library and does not require any additional Python packages.

| Source material | Where to start |
|---|---|
| 🎞️ Video | Export JPG frames with PotPlayer → batch-convert them to monochrome BMP with IrfanView |
| 🪄 GIF | Extract the frames and batch-convert them to monochrome BMP with IrfanView |
| 🖼️ Regular images | If the images already have the correct dimensions and monochrome format, start directly with Img2Lcd |

### Prepare the Image Frames for Your Source Type

#### 🎞️ Video: Export Frames with PotPlayer First

Use PotPlayer's continuous screenshot feature to save every frame as `BMP` in the same folder. Make a note of the export frame rate, because the `--fps` value passed to `h2bin.py` later should match it.

![PotPlayer frame capture menu](images/image-1.png)

Use the settings shown below:

![PotPlayer capture settings](images/image.png)
![PotPlayer output settings](images/image-2.png)

Let the video play to the end so that all frames are captured.

![Exported video frames](images/image-3.png)

#### 🪄 GIF: Extract Frames Directly with IrfanView

A GIF does not need to go through PotPlayer. Open it directly in IrfanView, extract every frame in order, and then use batch conversion to make all frames the same size, convert them to monochrome, and save them as BMP. Once that is done, continue with the Img2Lcd step below.

![Opening the GIF in IrfanView](images/image-4.png)
![IrfanView frame extraction menu](images/image-5.png)
![IrfanView frame extraction settings](images/image-6.png)

This produces a folder containing many frames:

![Extracted GIF frames](images/image-7.png)

You may find that the first image has different dimensions from the rest. If so, delete it.

![A frame with mismatched dimensions](images/image-12.png)

Next, use IrfanView to resize the images to `128x64`:

![IrfanView batch conversion](images/image-13.png)
![IrfanView resize settings](images/image-14.png)
![IrfanView monochrome settings](images/image-15.png)
![IrfanView batch input selection](images/image-16.png)

Choose the output directory:

![IrfanView output directory](images/image-17.png)

Then start the conversion.

> [!IMPORTANT]
> Check that every image uses the same format and dimensions. In the example below, another unusual frame was found. If an inconsistent frame remains, the finished video may appear to flash. Delete the incorrect frame when possible; if the original animation only contains a few frames, decide carefully before removing one.
> ![An inconsistent frame in the batch](images/image-18.png)

#### 🖼️ Regular Images: Preprocess Only When Needed

If your source is already one image, or a group of prepared images, you can start with Img2Lcd. Use IrfanView for a batch conversion first only when the dimensions or monochrome output still need to be standardized.

### Generate One `.c` File per Frame with Img2Lcd

![Opening the prepared image folder in Img2Lcd](images/image-8.png)

> Open the folder containing the images that have already been converted to the required pixel dimensions.
> The image shown in the screenshot is still in color, but that does not prevent the next step.

![Img2Lcd output configuration](images/image-9.png)

Img2Lcd writes the generated `.c` files to a `./batch` folder inside the image directory you selected. The program creates this folder automatically.

![Img2Lcd batch conversion](images/image-10.png)
![Generated frame C files](images/image-11.png)

### Merge the `.c` Files into One `.h` File

Run this command from the project root:

```bash
python tools/merge_img2lcd.py img2lcd_c/ merged_frames.h
```

![Running merge_img2lcd.py](images/image-19.png)

If the frame directory is outside the repository, wrap both the input and output paths in quotes:

```bash
python tools/merge_img2lcd.py "<Img2Lcd batch folder>" "<output header path>"
```

![Merging frames with absolute paths](images/image-20.png)

The merge tool reads only `.c` files in the top level of the selected directory and orders them using natural filename sorting.

### Generate the OVID `.BIN`

The following example uses 128×64 at 15 FPS:

```bash
python tools/h2bin.py merged_frames.h OUTPUT.BIN -W 128 -H 64 --fps 15
```

If the input and output are in other directories, put those paths in quotes as well:

```bash
python tools/h2bin.py "<merged header file>" "<output BIN path>" -W 128 -H 64 --fps 15
```

The width and height must match the settings used when generating the Img2Lcd data. The script checks that every array contains exactly `ceil(height/8) × width` bytes and reports the frame count, bytes per frame, total duration, and minimum OLED macros required by the firmware.

> [!TIP]
> `h2bin.py` generates the OVID v2 format used by the current firmware by default. It includes a header CRC16 and per-frame CRC32, making damaged frames easier to diagnose and preventing invalid frame data from being written directly to the OLED.

### Validate the File and Copy It to the SD Card

Run the validation command once after generating the file:

```bash
python tools/h2bin.py info OUTPUT.BIN
```

After confirming that the format, dimensions, frame count, FPS, and CRC results are correct, copy the `.BIN` file to the SD card's `/function` directory.

<details>
<summary><strong>Optional: Convert Directly from the Source CLI</strong></summary>

Without starting the GUI, you can call the same conversion core used by the desktop app. It accepts images, image folders, GIFs, and videos:

```bash
python -m pip install -r tools/requirements-converter.txt
python tools/media2ovid.py INPUT.mp4 OUTPUT.BIN -W 128 -H 64 --fps 15
```

This route is useful for automation and batch processing. The Img2Lcd workflow above makes it easier to inspect the sampling result of each frame according to the scan mode selected in the graphics tool.

</details>

<p align="right"><a href="#top">⬆️ Back to top</a></p>
