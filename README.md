# 展示今天的课程！

[![星标](https://img.shields.io/github/stars/Yersmagit/cw-easi-control?style=for-the-badge&color=orange&label=星标)](https://github.com/Yersmagit/cw-lessons-displayer)
[![开源许可](https://img.shields.io/badge/license-MIT-darkgreen.svg?label=开源许可证&style=for-the-badge)](https://github.com/Yersmagit/cw-lessons-displayer)
[![下载量](https://img.shields.io/github/downloads/Yersmagit/cw-easi-control/total.svg?label=下载量&color=green&style=for-the-badge)](https://github.com/Yersmagit/cw-lessons-displayer)


## 功能
- 展示今日的课程
- 可以根据设定自动化切换的熄屏模式和白板模式（此功能推荐在投影仪设备上使用）
- 其它。。。

## 效果
#### 浅色模式
<img width="648" height="375" alt="ed7aed86e4edb13547ea6a708b4bf76b" src="https://github.com/user-attachments/assets/6741f788-51a5-4106-8765-81c78002219f" />

#### 深色模式
<img width="648" height="375" alt="3507039ef9b7115de1eaa6f97506599b_0" src="https://github.com/user-attachments/assets/6c39138b-39c4-4a6e-ae31-42bbe7054b92" />

#### 熄屏模式
<img width="648" height="375" alt="42707a4d41ed98dac111384386cb1a68" src="https://github.com/user-attachments/assets/11c1bd63-7023-4d6a-8bab-bf5d98dac548" />

#### 白板模式
<img width="648" height="375" alt="7365d5f20debf762c1c7bc592f484bfc_0" src="https://github.com/user-attachments/assets/6ae70bbc-33dd-43a1-9dc5-4980fcc28aee" />

## 使用说明
### 初次打开
1. 打开插件
2. 尽情享用！

### 附加功能
> [!TIP]
> 这些功能更适合在投影仪设备上使用

- **手动打开或关闭熄屏模式或白板模式**
  - 在软件启动后，直接单击 UI 右侧的熄屏模式/白板模式切换按钮，即可打开相应的模式。
  - 打开相应模式后，单击屏幕右上角关闭按钮即可关闭。

- **自动化打开或关闭熄屏模式或白板模式**
  - **在 `./config/` 目录下打开 `data.json` ，可以编辑相应课程的自动化设置。**
    以下是示例的配置：
    ```json
    {
        "events":{
            "示例课程":{
                "click": "True",
                "time": 60,
                "mode": "blackboard"
            },
            "示例课程-2":{
                "click": "False",
                "time": -180,
                "mode": "whiteboard"
            }
        }
    }
    ```

  - 你可以在文件中修改 `示例课程` 为你想要设定的课程（包括 `课间` 和 `暂无课程` ）
  - `"time"` 后面的值用于设定在这节课上触发自动化的时间。正值代表在这节课进行了多久后触发，负值代表在这节课剩余多久时触发。格式为整型数字，单位秒。
  - `"click"` 后面的值用于设定触发自动化切换前是否允许用户操作。这是一个布尔值。如果值为`False`，则如果在 **从这节课开始**到**到达自动化切换触发时** 的这段时间内，检测到用户点击了键盘或鼠标的任意键，则不会在这节课上执行自动化；如果值为`True`，则插件无论如何都会在设定的时间触发自动化。
  - `"mode"` 后面的值用于设定执行的自动化操作。值只能是`"blackboard"`、`"whiteboard"`或`"none"`。`"blackboard"`代表切换至熄屏模式，`"whiteboard"`代表切换至白板模式，`"none"`代表关闭熄屏模式或白板模式。

> [!IMPORTANT]
> 此功能适合专业人士，不当操作可能导致软件崩溃

## 其它
### 许可证
本插件采用了 MIT 许可证，详情请查看 [此处](LICENSE)。
Copyright © 2025 Yersmagit.
