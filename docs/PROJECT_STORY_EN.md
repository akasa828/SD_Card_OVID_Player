# Why I Built This

[中文](PROJECT_STORY.md) · **English** · [Back to README](../README_EN.md)

This project was not supposed to become this complicated at first.

It started when I saw people using STM32 boards and all kinds of displays to play Bad Apple. I thought it looked fun, and a very simple idea came to mind: I wanted to build one too.

But if I was going to do it, I did not really want to put the video data directly into W25Q Flash. Capacity was one reason—one converted `bad_apple.bin` file was already close to 10 MB. More importantly, if I ever wanted to turn the experiment into a small player where files could be replaced freely, or several files could be stored at once, fixing one video inside Flash would not be a very good fit.

That led me to the SD card. It offered much more capacity, made files easy to replace, and felt a lot closer to my idea of a player than something that could only show the one video compiled into it.

Then came the next question:

How does an STM32 read a file from an SD card?

That was where things gradually started getting out of hand—in a good way.

To read a `.bin` file from the card, I started learning about SD card communication and the FatFs filesystem. Once I had solved where the file came from, I still needed to work out how to send the data I had read to the OLED.

My experience level was not very high at the time. Even moving from some of the code I had used before to the HAL library was already difficult for me. There were plenty of OLED drivers online, but finding one that really matched what I needed, used HAL, and provided a reasonably complete set of features was harder than expected. Some only displayed text, some had very limited drawing functions, and others still needed a lot of work after being ported.

I am also the kind of person who can copy some code, but if I cannot understand what I copied, I will probably not know how to change it later.

The project ended up sitting untouched for more than a month.

Eventually I realized that leaving it there was not going to help. Instead of waiting until I “knew everything” before coming back, it made more sense to get something working first and solve each problem when I reached it.

So I picked the project up again.

At the beginning, it was still a mixture of code from different places, with the simple goal of making the OLED light up, reading the SD card, and getting Bad Apple to play. As I became more familiar with each part, though, the project gradually developed its own structure and logic.

The OLED code stopped being limited to a few characters and slowly gained pixels, lines, shapes, images, and text. The part that had originally been assembled from drivers found elsewhere also became a HAL-based OLED driver that I could actually understand and modify myself.

Once Bad Apple was finally playing, another thought appeared:

If the SD card can hold files, why should the firmware only play one hard-coded file?

That led to file access, file selection, and a UI. Step by step, what began as a small experiment to “play Bad Apple on an STM32” turned into this project: a small player that reads files from an SD card, drives an OLED, and has its own interface and controls.

Looking back, the project ended up solving more than just “how to play Bad Apple on an STM32.”

On one side, I wanted to organize a HAL-based OLED driver that was reasonably complete and genuinely convenient to use, so that someone with a similar idea would not have to search through scattered code everywhere.

On the other, it became a fairly complete learning process for me:

finding code, combining it, trying to understand it, learning to modify it, designing features of my own, and finally turning an idea into something that actually runs.

As for that original idea of “playing Bad Apple on an STM32”...

I just did not expect it to take quite this much work to play one video.
