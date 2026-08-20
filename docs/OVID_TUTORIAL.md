<a id="top"></a>

# 🎬 生成 OVID 文件

[← 返回项目 README](../README.md)

> 以下 拿 `Bad Apple.mp4 举例`

由于`F103C8T6`不适合也不好直接塞个`MP4`解码器进去，导致步骤比较多，但是能播放已经很好了


```text
图片帧 → 黑白 BMP → Img2Lcd 单帧 .c → 合并 .h → OVID .BIN
```

仓库里会用到两个 Python 脚本：[`tools/merge_img2lcd.py`](../tools/merge_img2lcd.py) 负责合并视频帧取模得到的一系列`.c`文件 → `.h`文件，[`tools/h2bin.py`](../tools/h2bin.py) 负责生成和检查 OVID二进制文件。下面这条主流程只使用 Python 标准库，不需要另外安装 Python 包。

| 输入素材 | 从哪里开始 |
|---|---|
| 🎞️ 视频 | PotPlayer 导出 JPG 帧 → IrfanView 批量转黑白 BMP |
| 🪄 GIF | IrfanView 拆帧并批量转黑白 BMP |
| 🖼️ 普通图片 | 图片已经符合尺寸和黑白要求时，直接从 Img2Lcd 开始 |

###  按素材类型准备图片帧

#### 🎞️ 视频：先用 PotPlayer 导出帧

用 PotPlayer 的连续截图功能，把视频的每一帧保存为 `BMP` 并放进同一个文件夹。导出帧率要记下来，因为稍后传给 `h2bin.py` 的 `--fps` 应与这里一致。

![alt text](images/image-1.png)
按照这样设置
![alt text](images/image.png)
![alt text](images/image-2.png)
然后等待视频播放完成就将所有帧截取完了
![alt text](images/image-3.png)


#### 🪄 GIF：直接用 IrfanView 拆帧

GIF 不需要经过 PotPlayer。直接用 IrfanView 打开 GIF，把其中的所有帧拆出并按顺序保存，再使用批量转换功能统一尺寸、转成黑白图并输出为 BMP。处理完成后，直接继续下面的 Img2Lcd 步骤。

![alt text](images/image-4.png)
![alt text](images/image-5.png)
![alt text](images/image-6.png)

同样得到了很多帧

![alt text](images/image-7.png)

但是第一张你会发现大小和别的不一样，所以删掉就行

![alt text](images/image-12.png)

然后再用IrfanView处理尺寸成`128x64`

![alt text](images/image-13.png)
![alt text](images/image-14.png)
![alt text](images/image-15.png)
![alt text](images/image-16.png)

选择输出目录

![alt text](images/image-17.png)

随后开始即可

> [!IMPORTANT]
> 请检查各个图片是否格式一致，比如下面这里又发现有张不对劲的，否则到时候放出来就会“闪帧”，直接删除不对劲的图片即可，要是表情本身帧数不多，那还是别删了
> ![alt text](images/image-18.png)
#### 🖼️ 普通图片：按需要预处理

如果素材本来就是一张或一组已经处理好的图片，可以从 Img2Lcd 这一步开始；需要统一尺寸或黑白效果时，再先用 IrfanView 做一次批处理。



### 用 Img2Lcd 生成单帧 `.c`

![alt text](images/image-8.png)
> 打开的文件夹为存放已经转成规定像素规格的图像
> 图中的图像虽然是彩色的，但不影响继续操作

![alt text](images/image-9.png)
随后会将多个`.c`文件放在当前你选择的这个图片目录的`./batch`文件夹下，这个文件夹是程序自己生成的
![alt text](images/image-10.png)
![alt text](images/image-11.png)
### 把多个 `.c` 合并成单个 `.h`

在项目根目录执行：
```bash
python tools/merge_img2lcd.py img2lcd_c/ merged_frames.h
```
![alt text](images/image-19.png)

如果帧目录不在仓库中，可以给输入和输出路径加上引号：
```bash
python tools/merge_img2lcd.py "<Img2Lcd batch 文件夹>" "<输出头文件路径>"
```
![alt text](images/image-20.png)
合并工具只读取该目录第一层的 `.c` 文件，并按自然顺序排列

### 生成 OVID `.BIN`

下面以 128×64、15 FPS 为例：

```bash
python tools/h2bin.py merged_frames.h OUTPUT.BIN -W 128 -H 64 --fps 15
```
输入和输出位于其他目录时，同样给路径加上引号：
```bash
python tools/h2bin.py "<合并后的头文件>" "<输出 BIN 路径>" -W 128 -H 64 --fps 15
```

宽高必须与 Img2Lcd 取模时一致。脚本会检查每个数组是否正好等于 `ceil(height/8) × width`，并报告帧数、单帧字节数、总时长和固件至少需要的 OLED 宏。

> [!TIP]
> `h2bin.py` 默认生成当前固件使用的 OVID v2。它带有头部 CRC16 和逐帧 CRC32，发现坏帧时更容易诊断，也不会把损坏帧直接刷到 OLED。

### 检查并复制到 SD 卡

生成后先运行一次检查：

```bash
python tools/h2bin.py info OUTPUT.BIN
```

确认格式、宽高、帧数、FPS 和 CRC 都正常后，再把 `.BIN` 放入 SD 卡的 `/function` 目录。

<details>
<summary><strong>可选：直接从图片目录或 GIF 生成</strong></summary>

`h2bin.py` 仍然保留了直接读取图片和 GIF 的快捷方式。这条路线需要 Pillow：

```bash
python -m pip install Pillow
python tools/h2bin.py from-images frames/ OUTPUT.BIN -W 128 -H 64 --fps 15
```

它适合快速测试；上面的 Img2Lcd 流程更便于按照图形工具中的扫描方式检查每一帧取模结果。

</details>

<p align="right"><a href="#top">⬆️ 返回顶部</a></p>
