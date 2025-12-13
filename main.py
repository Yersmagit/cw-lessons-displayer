"""
main.py
ClassWidgets 今日课程显示插件
用于显示今日课程，并提供熄屏模式和白板模式
"""

import os
import json
import time
import logging
import configparser
from datetime import datetime, timedelta
from typing import Dict, Any
from PyQt5.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QSizePolicy, QPushButton, QSpacerItem
from PyQt5.QtCore import Qt, QObject, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap
from qfluentwidgets import isDarkTheme

import ctypes
from ctypes import wintypes

# 为插件创建独立的logger
logger = logging.getLogger("cw-lessons-displayer")

# 假设插件基类（根据实际项目结构调整导入路径）
try:
    from .ClassWidgets.base import PluginBase
except ImportError:
    # 如果导入失败，创建一个简单的基类
    class PluginBase:
        def __init__(self, app_context: Dict[str, Any], plugin_method: Any):
            self.app_contexts = app_context
            self.plugin_method = plugin_method
            self.plugin_name = "cw-lessons-displayer"
            self.plugin_version = "1.0.0"
            self.plugin_author = "Yersmagit"
            
        def execute(self):
            pass
            
        def stop(self):
            pass

class GlobalEventFilter(QObject):
    """全局事件监听器 - 使用轮询方式检测用户活动"""
    
    # 定义信号
    user_activity_detected = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.running = False
        self.poll_timer = None
        self.last_mouse_pos = None
        self.last_key_state = {}
        
        # 获取Windows API函数
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        
    def start_listening(self):
        """开始监听全局事件"""
        try:
            if self.running:
                logger.warning("全局事件监听器已经在运行")
                return
                
            logger.info("启动全局事件监听器（轮询模式）")
            
            # 初始化状态
            self.last_mouse_pos = self.get_mouse_position()
            self.last_key_state = self.get_key_states()
            
            # 创建轮询定时器
            self.poll_timer = QTimer()
            self.poll_timer.timeout.connect(self.check_user_activity)
            self.poll_timer.start(20)  # 每20毫秒检查一次
            
            self.running = True
            logger.info("全局事件监听器启动成功（轮询模式）")
            
        except Exception as e:
            logger.error(f"启动全局事件监听器失败: {e}")
    
    def get_mouse_position(self):
        """获取鼠标位置"""
        try:
            point = wintypes.POINT()
            if self.user32.GetCursorPos(ctypes.byref(point)):
                return (point.x, point.y)
            return None
        except:
            return None
    
    def get_key_states(self):
        """获取按键状态"""
        try:
            key_states = {}
            # 检查常用按键（A-Z, 0-9, 功能键等）
            for vk_code in range(1, 256):
                key_states[vk_code] = self.user32.GetAsyncKeyState(vk_code) & 0x8000 != 0
            return key_states
        except:
            return {}
    
    def check_user_activity(self):
        """检查用户活动"""
        try:
            # 检查鼠标点击
            current_mouse_pos = self.get_mouse_position()
            if (current_mouse_pos and self.last_mouse_pos and 
                current_mouse_pos != self.last_mouse_pos):
                # 检查鼠标按钮状态
                left_click = self.user32.GetAsyncKeyState(0x01) & 0x8000 != 0  # 左键
                right_click = self.user32.GetAsyncKeyState(0x02) & 0x8000 != 0  # 右键
                middle_click = self.user32.GetAsyncKeyState(0x04) & 0x8000 != 0  # 中键
                
                if left_click or right_click or middle_click:
                    self.user_activity_detected.emit()
                    logger.debug("检测到鼠标点击")
            
            # 检查键盘按键
            current_key_states = self.get_key_states()
            if self.last_key_state:
                for vk_code, pressed in current_key_states.items():
                    if pressed and not self.last_key_state.get(vk_code, False):
                        # 忽略某些系统键（如Shift、Ctrl、Alt等）
                        if vk_code not in [0x10, 0x11, 0x12, 0x5B, 0x5C]:  # Shift, Ctrl, Alt, Win键
                            self.user_activity_detected.emit()
                            logger.debug(f"检测到键盘按键: {vk_code}")
                            break
            
            # 更新状态
            self.last_mouse_pos = current_mouse_pos
            self.last_key_state = current_key_states
            
        except Exception as e:
            logger.error(f"检查用户活动失败: {e}")
    
    def stop_listening(self):
        """停止监听全局事件"""
        try:
            if not self.running:
                return
                
            logger.info("停止全局事件监听器")
            self.running = False
            
            if self.poll_timer:
                self.poll_timer.stop()
                self.poll_timer = None
            
            logger.info("全局事件监听器已停止")
            
        except Exception as e:
            logger.error(f"停止全局事件监听器失败: {e}")

class Plugin(PluginBase):
    """显示今日课程插件"""
    
    def __init__(self, app_context: Dict[str, Any], plugin_method: Any):
        # 首先调用父类初始化
        super().__init__(app_context, plugin_method)
        
        # 确保 app_contexts 属性存在
        if not hasattr(self, 'app_contexts'):
            self.app_contexts = app_context
        
        # 配置插件专用日志 - 修正为插件自己的目录
        base_directory = self.app_contexts.get('Base_Directory', '.')
        plugin_log_dir = os.path.join(base_directory, "plugins", "cw-lessons-displayer", "log")
        os.makedirs(plugin_log_dir, exist_ok=True)
        
        # 配置独立的日志处理器
        self.setup_logging(plugin_log_dir)
        
        self.plugin_name = "今日课程"
        self.display_widgets = []  # 当前显示的组件列表
        self.previous_widgets = [] # 上一次的组件列表，用于检测变化
        self.widgets_width = {}    # 组件宽度字典
        self.total_width = 0       # 总宽度
        self.ui_widget = None      # UI部件
        self.backgnd_frame = None  # 背景框架
        self.ui_initialized = False # UI初始化状态
        self.lesson_layout = None  # 课程布局
        
        self.previous_lessons = {}  # 上一次的课程数据
        self.current_course_id = None  # 当前课程ID
        self.course_frames = {}  # 存储课程框架的字典 {course_id: frame}
        self.previous_highlight_id = None  # 之前高亮的课程ID
        self.current_state = None  # 当前状态
        
        # 主题状态跟踪
        try:
            self.current_theme_dark = isDarkTheme()  # 当前主题状态
        except:
            self.current_theme_dark = False  # 默认值

        # 按钮引用
        self.pushButton_switch = None
        self.pushButton_light = None
        self.pushButton_dark = None

        # 熄屏模式相关变量
        self.blackboard_widget = None  # 熄屏模式UI部件
        self.blackboard_lesson_layout = None  # 熄屏模式课程布局
        self.blackboard_course_frames = {}  # 熄屏模式课程框架字典
        self.is_blackboard_mode = False  # 是否处于熄屏模式
        self.blackboard_current_course_id = None  # 熄屏模式当前课程ID
        self.blackboard_previous_highlight_id = None  # 熄屏模式之前高亮的课程ID
        self.blackboard_current_state = None  # 熄屏模式当前状态

        # 白板模式相关变量
        self.whiteboard_widget = None  # 白板模式UI部件
        self.whiteboard_lesson_layout = None  # 白板模式课程布局
        self.whiteboard_course_frames = {}  # 白板模式课程框架字典
        self.is_whiteboard_mode = False  # 是否处于白板模式
        self.whiteboard_current_course_id = None  # 白板模式当前课程ID
        self.whiteboard_previous_highlight_id = None  # 白板模式之前高亮的课程ID
        self.whiteboard_current_state = None  # 白板模式当前状态

        # 进度条动画相关变量
        self.blackboard_progress_animation = None
        self.whiteboard_progress_animation = None
        self.current_blackboard_progress = 0
        self.current_whiteboard_progress = 0
        
        # 自动化功能相关变量
        self.automation_settings = {}  # 存储自动化设置
        self.current_lesson_name = None  # 当前课程名称
        self.previous_lesson_name = None  # 上一次课程名称
        self.lesson_start_time = None  # 课程开始时间
        self.user_activity_detected = False  # 用户是否有操作
        self.automation_triggered = False  # 自动化是否已触发
        self.tip_window = None  # 提示窗口
        self.tip_timer = None  # 提示计时器
        self.automation_timer = None  # 自动化计时器

        # 事件过滤器
        self.global_event_filter = None

        # 提示窗口动画相关变量
        self.tip_animation_group = None
        self.tip_close_animation_group = None

        # 自动化相关变量
        self.current_automation_mode = None  # 当前自动化模式
        self.realtime_check_timer = None     # 实时监测计时器

        # 主组件动画相关变量
        self.main_widget_animation = None  # 主组件动画
        self.is_main_widget_visible = False  # 主组件是否可见
        self.pending_width_update = False  # 是否有待处理的宽度更新

        # 小组件列表状态跟踪
        self.has_valid_widgets = False  # 是否有有效的小组件列表
        self.initial_widget_check_done = False  # 初始小组件检查是否完成

        # 鼠标隐藏相关变量
        self.mouse_hidden = False  # 鼠标是否已隐藏
        self.mouse_stationary_time = 0  # 鼠标静止时间（秒）
        self.last_mouse_position = None  # 上次鼠标位置
        self.mouse_hide_timer = None  # 鼠标隐藏计时器
        self.mouse_check_interval = 100  # 鼠标检查间隔（毫秒）
        self.mouse_hide_delay = 2000  # 鼠标隐藏延迟（毫秒）
        
        # 明日课程相关变量
        self.tomorrow_course_settings = {}  # 明日课程设置
        self.showing_tomorrow_courses = False  # 是否正在显示明日课程
        self.tomorrow_course_icon_label = None  # 明日课程图标标签
        self.tomorrow_course_text_label = None  # 明日课程文本标签
        self.tomorrow_course_spacer = None  # 明日课程间隔
        
        logger.info("今日课程 插件初始化完成")
    
    def setup_logging(self, log_dir):
        """设置独立的日志系统 - 使用基本的FileHandler避免导入问题"""
        # 移除可能存在的现有处理器
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        
        # 创建基本的文件处理器（不使用RotatingFileHandler）
        log_file = os.path.join(log_dir, "cw-lessons-displayer.log")
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        
        # 创建格式化器
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s'
        )
        file_handler.setFormatter(formatter)
        
        # 设置日志级别
        logger.setLevel(logging.DEBUG)
        file_handler.setLevel(logging.DEBUG)
        
        # 添加处理器
        logger.addHandler(file_handler)
        
        # 避免日志传播到根logger
        logger.propagate = False

    def load_automation_settings(self):
        """加载自动化设置"""
        try:
            # 安全检查
            if not hasattr(self, 'app_contexts') or self.app_contexts is None:
                logger.error("app_contexts 未初始化，无法加载自动化设置")
                return
                
            base_directory = self.app_contexts.get('Base_Directory', '.')
            settings_path = os.path.join(base_directory, "plugins", "cw-lessons-displayer", "config", "data.json")
            
            logger.info(f"尝试加载自动化设置文件: {settings_path}")
            
            if os.path.exists(settings_path):
                with open(settings_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.automation_settings = data.get('events', {})
                    self.tomorrow_course_settings = data.get('tomorrow_course', {})
                
                # 详细日志记录加载的设置
                logger.info(f"成功加载自动化设置，共 {len(self.automation_settings)} 个课程设置")
                for course_name, settings in self.automation_settings.items():
                    logger.info(f"课程 '{course_name}': time={settings.get('time')}, "
                            f"click={settings.get('click')}, mode={settings.get('mode')}")
                
                # 记录明日课程设置
                logger.info(f"明日课程设置: {self.tomorrow_course_settings}")
            else:
                logger.warning(f"自动化设置文件不存在: {settings_path}")
                self.automation_settings = {}
                self.tomorrow_course_settings = {}
                logger.info("使用空的自动化设置")
                
        except Exception as e:
            logger.error(f"加载自动化设置失败: {e}")
            self.automation_settings = {}
            self.tomorrow_course_settings = {}

    def init_ui(self, theme_changed=False):
        """初始化UI"""
        try:
            logger.info(f"开始初始化UI, theme_changed={theme_changed}")
            
            # 安全检查
            if not hasattr(self, 'app_contexts') or self.app_contexts is None:
                logger.error("app_contexts 未初始化，无法初始化UI")
                return
                
            from PyQt5 import uic

            # 颜色模式
            is_dark = isDarkTheme()
            logger.info(f"当前主题状态: {'深色' if is_dark else '浅色'}")
            
            # 更新当前主题状态
            self.current_theme_dark = is_dark
            
            # 获取UI文件路径
            base_directory = self.app_contexts.get('Base_Directory', '.')

            if is_dark:
                ui_file_path = os.path.join(base_directory, "plugins", "cw-lessons-displayer", "ui", "default_dark.ui")
            else:
                ui_file_path = os.path.join(base_directory, "plugins", "cw-lessons-displayer", "ui", "default_light.ui")
            
            logger.info(f"尝试加载UI文件: {ui_file_path}")
            
            if not os.path.exists(ui_file_path):
                logger.error(f"UI文件不存在: {ui_file_path}")
                self.ui_initialized = False
                return
                
            # 如果之前已经有UI部件，先清理
            if self.ui_widget:
                logger.info("清理旧UI部件")
                self.ui_widget.deleteLater()
                self.ui_widget = None
                self.lesson_layout = None
                self.course_frames.clear()
                self.pushButton_switch = None
                self.pushButton_light = None
                self.pushButton_dark = None
                self.tomorrow_course_icon_label = None
                self.tomorrow_course_text_label = None
                self.tomorrow_course_spacer = None
                
            # 加载UI文件
            self.ui_widget = uic.loadUi(ui_file_path)
            
            if self.ui_widget is None:
                logger.error("UI文件加载失败，返回None")
                self.ui_initialized = False
                return
                
            logger.info("UI文件加载成功")
            
            # 设置窗口属性
            self.ui_widget.setWindowFlags(
                Qt.FramelessWindowHint | 
                Qt.WindowStaysOnBottomHint |  # 置底显示
                Qt.Tool
            )
            self.ui_widget.setAttribute(Qt.WA_TranslucentBackground)
            self.ui_widget.setAttribute(Qt.WA_ShowWithoutActivating)
            
            # 注意：这里不设置透明度为0，而是保持默认（不透明）
            # 这样插件启动后就能立即显示
            logger.info("UI部件创建完成，准备显示")
            
            # 获取课程布局
            self.lesson_layout = self.ui_widget.findChild(QHBoxLayout, "horizontalLayout_lesson_list")
            if not self.lesson_layout:
                logger.error("未找到horizontalLayout_lesson_list布局")
                self.ui_initialized = False
                return
                
            logger.info("找到课程布局，准备显示课程")
            
            # 获取按钮引用
            self.pushButton_switch = self.ui_widget.findChild(QPushButton, "pushButton_switch")
            self.pushButton_light = self.ui_widget.findChild(QPushButton, "pushButton_light")
            self.pushButton_dark = self.ui_widget.findChild(QPushButton, "pushButton_dark")
            
            # 获取明日课程相关控件
            self.tomorrow_course_text_label = self.ui_widget.findChild(QLabel, "tomorrow_course_text")
            horizontal_spacer_fixed_left_2 = self.ui_widget.findChild(QObject, "horizontalSpacer_fixed_left_2")
            
            # 设置按钮事件
            self.setup_button_events()
            
            # 设置按钮悬停样式
            self.setup_button_styles()
            
            # 初始设置
            self.ui_widget.setFixedHeight(74)
            self.ui_initialized = True
            
            # 重置主组件可见状态
            self.is_main_widget_visible = False
            
            # 初始隐藏明日课程相关控件
            if self.tomorrow_course_text_label:
                self.tomorrow_course_text_label.setVisible(False)
            if horizontal_spacer_fixed_left_2:
                horizontal_spacer_fixed_left_2.setVisible(False)
                
            logger.info("UI初始化成功，主组件状态重置为不可见")
            
        except Exception as e:
            logger.error(f"初始化UI失败: {e}")
            self.ui_initialized = False
    
    def fade_in_main_widget(self):
        """淡入主组件"""
        try:
            logger.info(f"淡入方法被调用 - 当前状态: is_main_widget_visible={self.is_main_widget_visible}, ui_widget exists={self.ui_widget is not None}")
            
            if self.is_main_widget_visible:
                logger.warning("主组件已经可见，跳过淡入")
                return
                
            if not self.ui_widget:
                logger.error("UI部件不存在，无法淡入")
                return
                
            logger.info("开始淡入主组件")
            
            from PyQt5.QtCore import QPropertyAnimation, QEasingCurve
            
            # 确保窗口显示
            self.ui_widget.show()
            logger.info(f"UI部件显示状态: {self.ui_widget.isVisible()}")
            
            # 创建淡入动画
            self.main_widget_animation = QPropertyAnimation(self.ui_widget, b"windowOpacity")
            self.main_widget_animation.setDuration(500)  # 500毫秒
            self.main_widget_animation.setStartValue(0.0)
            self.main_widget_animation.setEndValue(1.0)
            self.main_widget_animation.setEasingCurve(QEasingCurve.OutCubic)
            
            # 动画完成回调
            self.main_widget_animation.finished.connect(self._on_fade_in_finished)
            
            # 开始动画
            self.main_widget_animation.start()
            logger.info("淡入动画已启动")
            
        except Exception as e:
            logger.error(f"淡入主组件失败: {e}", exc_info=True)

    def _trigger_theme_change_fade_in(self):
        """主题变化后触发淡入"""
        try:
            if not self.ui_initialized or not self.ui_widget:
                logger.warning("UI未正确初始化，无法触发主题变化淡入")
                return
                
            logger.info("主题变化后触发自动淡入")
            
            # 检查是否有有效的课程数据
            current_lessons = self.app_contexts.get('Current_Lessons', {})
            if current_lessons:
                # 有课程数据，直接淡入
                self.fade_in_main_widget()
            else:
                # 没有课程数据，等待widget变化检测触发淡入
                logger.info("暂无课程数据，等待widget变化检测触发淡入")
                
        except Exception as e:
            logger.error(f"触发主题变化淡入失败: {e}")

    def fade_out_main_widget(self):
        """淡出主组件"""
        try:
            if not self.is_main_widget_visible or not self.ui_widget:
                return
                
            logger.info("开始淡出主组件")
            
            from PyQt5.QtCore import QPropertyAnimation, QEasingCurve
            
            # 创建淡出动画
            self.main_widget_animation = QPropertyAnimation(self.ui_widget, b"windowOpacity")
            self.main_widget_animation.setDuration(500)  # 500毫秒
            self.main_widget_animation.setStartValue(1.0)
            self.main_widget_animation.setEndValue(0.0)
            self.main_widget_animation.setEasingCurve(QEasingCurve.OutCubic)
            
            # 动画完成回调
            self.main_widget_animation.finished.connect(self._on_fade_out_finished)
            
            # 开始动画
            self.main_widget_animation.start()
            
        except Exception as e:
            logger.error(f"淡出主组件失败: {e}")

    def _on_fade_in_finished(self):
        """淡入动画完成回调"""
        try:
            self.is_main_widget_visible = True
            logger.info("主组件淡入完成")
            
            # 清理动画对象
            if self.main_widget_animation:
                self.main_widget_animation.deleteLater()
                self.main_widget_animation = None
                
            # 如果有待处理的宽度更新，执行更新
            if self.pending_width_update:
                logger.info("执行待处理的宽度更新")
                self.pending_width_update = False
                self.update_ui_width()
                
        except Exception as e:
            logger.error(f"淡入动画完成处理失败: {e}")

    def _on_fade_out_finished(self):
        """淡出动画完成回调"""
        try:
            self.is_main_widget_visible = False
            logger.info("主组件淡出完成")
            
            # 清理动画对象
            if self.main_widget_animation:
                self.main_widget_animation.deleteLater()
                self.main_widget_animation = None
                
            # 如果有待处理的宽度更新，执行更新并淡入
            if self.pending_width_update:
                logger.info("执行待处理的宽度更新并淡入")
                self.pending_width_update = False
                self.update_ui_width()
                # 短暂延迟后淡入，确保宽度更新完成
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(50, self.fade_in_main_widget)
                
        except Exception as e:
            logger.error(f"淡出动画完成处理失败: {e}")
    
    def get_subject_abbreviation(self, subject_name):
        """获取课程缩写"""
        try:
            base_directory = self.app_contexts.get('Base_Directory', '.')
            subject_config_path = os.path.join(base_directory, "config", "data", "subject.json")
            
            if not os.path.exists(subject_config_path):
                logger.warning(f"subject.json文件不存在: {subject_config_path}")
                return subject_name[0] if subject_name else " "
            
            with open(subject_config_path, 'r', encoding='utf-8') as f:
                subject_config = json.load(f)
            
            # 在subject_abbreviation中查找
            abbreviations = subject_config.get('subject_abbreviation', {})
            if subject_name in abbreviations:
                abbreviation = abbreviations[subject_name].strip()  # 去除多余空格
                return abbreviation if abbreviation else subject_name[0]
            
            # 如果没找到，返回第一个字符
            return subject_name[0] if subject_name else " "
            
        except Exception as e:
            logger.error(f"获取课程缩写失败: {e}")
            return subject_name[0] if subject_name else " "
    
    def group_lessons_by_period(self, lessons_dict):
        """按时间段分组课程"""
        groups = {}
        for key, lesson_name in lessons_dict.items():
            if len(key) >= 2:
                period = key[1]  # 第二个字符代表时间段
                if period not in groups:
                    groups[period] = []
                # 获取课程缩写
                abbreviation = self.get_subject_abbreviation(lesson_name)
                groups[period].append(abbreviation)
        
        # 按时间段排序
        sorted_groups = dict(sorted(groups.items()))
        return sorted_groups
    
    def calculate_current_course(self):
        """计算当前课程"""
        try:
            # 获取必要数据
            current_time_str = self.app_contexts.get('Current_Time', '00:00:00')
            current_part = self.app_contexts.get('Current_Part', (None, 0))
            timeline_data = self.app_contexts.get('Timeline_Data', {})
            state = self.app_contexts.get('State', 0)
            
            # 解析当前时间
            from datetime import datetime, timedelta
            current_time = datetime.strptime(current_time_str, '%H:%M:%S').time()
            
            # 获取当前节点开始时间
            node_start_datetime, node_index = current_part
            if not node_start_datetime:
                logger.warning("未获取到节点开始时间")
                return None
                
            node_start_time = node_start_datetime.time()
            
            # 获取当前节点的活动
            node_activities = []
            for key, duration in timeline_data.items():
                if len(key) >= 2 and key[1] == str(node_index):
                    node_activities.append((key, int(duration)))
            
            if not node_activities:
                logger.debug(f"未找到节点 {node_index} 的活动数据")
                return None
            
            # 按照正确的顺序排序：先按第三个字符（活动序号）排序，再按第一个字符（活动类型）排序
            # 确保同一序号的活动，课程(a)排在课间(f)之前
            def activity_sort_key(item):
                activity_id = item[0]
                # 第三个字符是活动序号
                activity_number = activity_id[2] if len(activity_id) >= 3 else '0'
                # 第一个字符是活动类型
                activity_type = activity_id[0]
                # 先按活动序号排序，再按活动类型排序（a在f之前）
                # 将活动序号转换为整数进行排序，确保数字顺序正确
                return (int(activity_number) if activity_number.isdigit() else 0, activity_type)
            
            node_activities.sort(key=activity_sort_key)
            
            # 计算每个活动的开始时间
            activity_start_times = {}
            current_time_accumulated = datetime.combine(datetime.today(), node_start_time)
            
            # 按照排序后的顺序处理活动
            for activity_id, duration in node_activities:
                activity_start_times[activity_id] = current_time_accumulated.time()
                current_time_accumulated += timedelta(minutes=duration)
            
            # 节点结束时间
            node_end_time = current_time_accumulated.time()
            
            # 确定当前活动
            current_activity_id = None
            
            # 如果当前时间在节点开始之前，选择第一个课程
            if current_time < node_start_time:
                # 找到第一个课程活动（以'a'开头的活动）
                for activity_id, _ in node_activities:
                    if activity_id.startswith('a'):
                        current_activity_id = activity_id
                        break
            # 如果当前时间超过节点结束时间，返回None
            elif current_time >= node_end_time:
                logger.debug("当前时间超过节点结束时间")
                return None
            else:
                # 在当前时间范围内，找到当前活动
                for i, (activity_id, duration) in enumerate(node_activities):
                    start_time = activity_start_times[activity_id]
                    activity_end_time = (datetime.combine(datetime.today(), start_time) + 
                                    timedelta(minutes=duration)).time()
                    
                    if start_time <= current_time < activity_end_time:
                        # 如果是课间活动（以'f'开头），则选择下一个课程
                        if activity_id.startswith('f'):
                            # 找到下一个课程活动
                            next_activities = node_activities[i+1:]
                            for next_id, _ in next_activities:
                                if next_id.startswith('a'):
                                    current_activity_id = next_id
                                    break
                        else:
                            current_activity_id = activity_id
                        break
                
                # 如果没有找到匹配的活动，选择最后一个课程
                if not current_activity_id:
                    for activity_id, _ in reversed(node_activities):
                        if activity_id.startswith('a'):
                            current_activity_id = activity_id
                            break
            
            return current_activity_id
            
        except Exception as e:
            logger.error(f"计算当前课程失败: {e}")
            return None
        
    def get_current_activity_time_info(self):
        """获取当前活动的时间信息（总时长和剩余时间）
        Returns:
            tuple: (total_seconds, remaining_seconds, current_activity_id, state) 或 (None, None, None, None)
        """
        try:
            # 获取必要数据
            current_time_str = self.app_contexts.get('Current_Time', '00:00:00')
            current_part = self.app_contexts.get('Current_Part', (None, 0))
            timeline_data = self.app_contexts.get('Timeline_Data', {})
            state = self.app_contexts.get('State', 0)
            
            # 解析当前时间
            from datetime import datetime, timedelta
            current_time = datetime.strptime(current_time_str, '%H:%M:%S').time()
            
            # 获取当前节点开始时间
            node_start_datetime, node_index = current_part
            if not node_start_datetime:
                logger.warning("未获取到节点开始时间")
                return None, None, None, None
                
            node_start_time = node_start_datetime.time()
            
            # 获取当前节点的活动
            node_activities = []
            for key, duration in timeline_data.items():
                if len(key) >= 2 and key[1] == str(node_index):
                    node_activities.append((key, int(duration)))
            
            if not node_activities:
                logger.warning(f"未找到节点 {node_index} 的活动数据")
                return None, None, None, None
            
            # 按照正确的顺序排序：先按第三个字符（活动序号）排序，再按第一个字符（活动类型）排序
            def activity_sort_key(item):
                activity_id = item[0]
                activity_number = activity_id[2] if len(activity_id) >= 3 else '0'
                activity_type = activity_id[0]
                return (int(activity_number) if activity_number.isdigit() else 0, activity_type)
            
            node_activities.sort(key=activity_sort_key)
            
            # 计算每个活动的开始时间和结束时间
            activity_times = {}
            current_time_accumulated = datetime.combine(datetime.today(), node_start_time)
            
            for activity_id, duration in node_activities:
                start_time = current_time_accumulated.time()
                end_time = (current_time_accumulated + timedelta(minutes=duration)).time()
                activity_times[activity_id] = {
                    'start': start_time,
                    'end': end_time,
                    'duration_minutes': duration,
                    'duration_seconds': duration * 60
                }
                current_time_accumulated += timedelta(minutes=duration)
            
            # 节点结束时间
            node_end_time = current_time_accumulated.time()
            
            # 确定当前活动
            current_activity_id = None
            current_state = state
            
            # 如果当前时间在节点开始之前，选择第一个活动
            if current_time < node_start_time:
                current_activity_id = node_activities[0][0]
                current_state = 0  # 设置为课间状态
                
                # 计算剩余时间：从当前时间到节点开始时间
                node_start_datetime_obj = datetime.combine(datetime.today(), node_start_time)
                calibrated_datetime = datetime.combine(datetime.today(), current_time)
                remaining_timedelta = node_start_datetime_obj - calibrated_datetime
                remaining_seconds = max(0, int(remaining_timedelta.total_seconds()))
                
                # 总时长设为None，表示活动尚未开始
                total_seconds = None
                
                ### logger.debug(f"当前时间在节点开始之前，当前活动: {current_activity_id}, 剩余时间: {remaining_seconds}秒, 状态: {current_state}")
                
                return total_seconds, remaining_seconds, current_activity_id, current_state
            
            # 如果当前时间超过节点结束时间，返回None
            elif current_time >= node_end_time:
                logger.debug("当前时间超过节点结束时间")
                return None, None, None, None
            else:
                # 在当前时间范围内，找到当前活动
                for activity_id, duration in node_activities:
                    start_time = activity_times[activity_id]['start']
                    end_time = activity_times[activity_id]['end']
                    
                    if start_time <= current_time < end_time:
                        current_activity_id = activity_id
                        # 如果是课间活动，状态为0；如果是课程活动，状态为1
                        current_state = 0 if activity_id.startswith('f') else 1
                        break
            
            if not current_activity_id:
                logger.debug("未找到当前活动")
                return None, None, None, None
            
            # 计算剩余时间
            activity_end_datetime = datetime.combine(datetime.today(), activity_times[current_activity_id]['end'])
            calibrated_datetime = datetime.combine(datetime.today(), current_time)
            remaining_timedelta = activity_end_datetime - calibrated_datetime
            remaining_seconds = max(0, int(remaining_timedelta.total_seconds()))
            
            total_seconds = activity_times[current_activity_id]['duration_seconds']
            
            ### logger.debug(f"当前活动: {current_activity_id}, 总时长: {total_seconds}秒, 剩余时间: {remaining_seconds}秒, 状态: {current_state}")
            
            return total_seconds, remaining_seconds, current_activity_id, current_state
            
        except Exception as e:
            logger.error(f"获取当前活动时间信息失败: {e}")
            return None, None, None, None
    
    def create_lesson_frame(self, abbreviation, course_id):
        """创建课程显示框架"""
        # 当前主题
        is_dark = isDarkTheme()

        try:
            # 创建框架
            frame = QFrame()
            frame.setObjectName(f"frame_{course_id}")  # 设置对象名称用于标识
            frame.setMinimumSize(40, 40)
            frame.setMaximumSize(16777215, 40)
            frame.setStyleSheet("border-radius: 20px; background-color: none")
            frame.setFrameShape(QFrame.StyledPanel)
            frame.setFrameShadow(QFrame.Raised)
            
            # 创建布局
            layout = QHBoxLayout(frame)
            layout.setSpacing(0)
            layout.setContentsMargins(6, 0, 6, 0)
            
            # 创建标签
            label = QLabel(abbreviation)
            label.setObjectName(f"label_{course_id}")  # 设置对象名称
            label.setFont(self.create_lesson_font())
            if is_dark:
                label.setStyleSheet("border: none; color: rgb(255, 255, 255); font-weight: bold; background: none;")
            else:
                label.setStyleSheet("border: none; color: rgb(0, 0, 0); font-weight: bold; background: none;")
            label.setTextFormat(Qt.PlainText)
            label.setAlignment(Qt.AlignLeading | Qt.AlignLeft | Qt.AlignVCenter)
            
            layout.addWidget(label)
            
            return frame
            
        except Exception as e:
            logger.error(f"创建课程框架失败: {e}")
            return None
    
    def create_lesson_font(self):
        """创建课程字体"""
        from PyQt5.QtGui import QFont
        font = QFont("HarmonyOS Sans SC", 21)
        font.setBold(True)
        return font
    
    def create_divider(self):
        """创建分隔线"""
        # 当前主题
        is_dark = isDarkTheme()

        try:
            divider = QLabel("|")
            divider.setFont(self.create_lesson_font())
            if is_dark:
                divider.setStyleSheet("border: none; color: rgb(255, 255, 255); font-weight: bold; background: none;")
            else:
                divider.setStyleSheet("border: none; color: rgb(0, 0, 0); font-weight: bold; background: none;")
            divider.setTextFormat(Qt.PlainText)
            divider.setAlignment(Qt.AlignCenter)
            return divider
        except Exception as e:
            logger.error(f"创建分隔线失败: {e}")
            return None
    
    def create_spacer(self, width, fixed=True):
        """创建间隔"""
        try:
            from PyQt5.QtWidgets import QSpacerItem
            from PyQt5.QtCore import QSize
            
            size_policy = QSizePolicy.Fixed if fixed else QSizePolicy.Expanding
            spacer = QSpacerItem(width, 20, size_policy, QSizePolicy.Minimum)
            return spacer
        except Exception as e:
            logger.error(f"创建间隔失败: {e}")
            return None
    
    def clear_lesson_layout(self):
        """清空课程布局"""
        if not self.lesson_layout:
            return
            
        # 清空课程框架字典
        self.course_frames.clear()
        
        # 移除所有子项
        while self.lesson_layout.count():
            item = self.lesson_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.spacerItem():
                self.lesson_layout.removeItem(item)
        
    def display_lessons(self):
        """显示课程"""
        try:
            if not self.lesson_layout:
                logger.error("课程布局未初始化")
                return
                
            # 获取当前课程
            current_lessons = self.app_contexts.get('Current_Lessons', {})
            if not current_lessons:
                logger.info("没有找到当前课程数据")
                return
                
            ### logger.info(f"获取到课程数据: {current_lessons}")
            
            # 清空课程框架字典和状态
            self.course_frames.clear()
            self.current_course_id = None
            self.previous_highlight_id = None
            self.current_state = None  # 重置状态
            
            # 按时间段分组
            lesson_groups = self.group_lessons_by_period(current_lessons)
            ### logger.info(f"分组后的课程: {lesson_groups}")
            
            # 清空现有布局
            self.clear_lesson_layout()
            
            # 动态创建课程显示
            group_count = len(lesson_groups)
            for i, (period, lessons) in enumerate(lesson_groups.items()):
                # 获取这个时间段的所有课程ID
                period_course_ids = [key for key in current_lessons.keys() if key[1] == period]
                
                # 添加本组的课程
                for j, (course_id, abbreviation) in enumerate(zip(period_course_ids, lessons)):
                    frame = self.create_lesson_frame(abbreviation, course_id)
                    if frame:
                        self.lesson_layout.addWidget(frame)
                        # 存储课程框架引用
                        self.course_frames[course_id] = frame
                        ### logger.debug(f"添加课程框架: {abbreviation} (ID: {course_id})")
                    
                    # 课程之间添加6px间隔（最后一个课程后不添加）
                    if j < len(lessons) - 1:
                        spacer = self.create_spacer(6)  # 今日课程使用6px间隔
                        if spacer:
                            self.lesson_layout.addItem(spacer)
                
                # 组之间添加分隔线（最后一组后不添加）
                if i < group_count - 1:
                    # 添加10px间隔
                    spacer_before = self.create_spacer(10)
                    if spacer_before:
                        self.lesson_layout.addItem(spacer_before)
                    
                    # 添加分隔线
                    divider = self.create_divider()
                    if divider:
                        self.lesson_layout.addWidget(divider)
                    
                    # 添加10px间隔
                    spacer_after = self.create_spacer(10)
                    if spacer_after:
                        self.lesson_layout.addItem(spacer_after)
            
            logger.info("课程显示更新完成")
            
        except Exception as e:
            logger.error(f"显示课程失败: {e}")

    def update_current_course_highlight(self):
        """更新当前课程高亮显示"""
        try:
            # 计算当前课程
            current_course_id = self.calculate_current_course()
            current_state = self.app_contexts.get('State', 0)
            
            # 如果当前课程和状态都没有变化，直接返回
            if (current_course_id == self.current_course_id and 
                current_state == self.current_state):
                return
                
            # 如果当前课程ID为None，清除所有高亮
            if current_course_id is None:
                self.clear_main_ui_highlight()
                return
                
            # 移除之前的高亮
            if self.previous_highlight_id and self.previous_highlight_id in self.course_frames:
                previous_frame = self.course_frames[self.previous_highlight_id]
                previous_frame.setStyleSheet("border-radius: 20px; background-color: none")
                
                # 恢复标签颜色
                label = previous_frame.findChild(QLabel)
                if label:
                    if self.current_theme_dark:
                        label.setStyleSheet("border: none; color: rgb(255, 255, 255); font-weight: bold; background: none;")
                    else:
                        label.setStyleSheet("border: none; color: rgb(0, 0, 0); font-weight: bold; background: none;")
            
            # 设置新的高亮
            if current_course_id and current_course_id in self.course_frames:
                current_frame = self.course_frames[current_course_id]
                
                # 根据状态设置颜色
                if current_state == 0:  # 课间
                    bg_color = "#57c7a5"
                else:  # 上课
                    bg_color = "#e98f83"
                    
                current_frame.setStyleSheet(f"border-radius: 20px; background-color: {bg_color};")
                
                # 设置标签颜色为白色
                label = current_frame.findChild(QLabel)
                if label:
                    label.setStyleSheet("border: none; color: #ffffff; font-weight: bold; background: none;")
                
                # 更新状态
                self.previous_highlight_id = current_course_id
                self.current_course_id = current_course_id
                self.current_state = current_state
                
                logger.debug(f"更新课程高亮: {current_course_id}, 状态: {current_state}, 颜色: {bg_color}")
            
        except Exception as e:
            logger.error(f"更新课程高亮失败: {e}")
            # 出错时清除高亮
            self.clear_main_ui_highlight()

    def clear_main_ui_highlight(self):
        """清除主UI的高亮显示"""
        try:
            if not self.course_frames:
                return
                
            # 移除所有高亮
            for course_id, frame in self.course_frames.items():
                frame.setStyleSheet("border-radius: 20px; background-color: none")
                label = frame.findChild(QLabel)
                if label:
                    if self.current_theme_dark:
                        label.setStyleSheet("border: none; color: rgb(255, 255, 255); font-weight: bold; background: none;")
                    else:
                        label.setStyleSheet("border: none; color: rgb(0, 0, 0); font-weight: bold; background: none;")
            
            # 重置状态
            self.previous_highlight_id = None
            self.current_course_id = None
            self.current_state = None
            
            logger.debug("已清除主UI高亮显示")
            
        except Exception as e:
            logger.error(f"清除主UI高亮失败: {e}")
        
    def print_all_children(self, widget, level=0):
        """打印所有子组件信息（用于调试）"""
        try:
            indent = "  " * level
            if hasattr(widget, 'objectName'):
                name = widget.objectName() or "未命名"
                logger.debug(f"{indent}{type(widget).__name__}: {name}")
            else:
                logger.debug(f"{indent}{type(widget).__name__}")
                
            for child in widget.children():
                self.print_all_children(child, level + 1)
        except Exception as e:
            logger.error(f"打印子组件信息失败: {e}")
        
    def execute(self):
        """启动插件"""
        # 安全检查：确保 app_contexts 存在
        if not hasattr(self, 'app_contexts') or self.app_contexts is None:
            logger.error("app_contexts 未正确初始化，无法启动插件")
            return
        
        logger.info(f"{self.plugin_name} 已启动，UI初始化状态: {self.ui_initialized}")
        
        # 加载自动化设置（在app_contexts可用后）
        self.load_automation_settings()
        
        # 初始化UI（在app_contexts可用后）
        self.init_ui()
        
        # 启动全局事件监听器
        try:
            self.global_event_filter = GlobalEventFilter()
            self.global_event_filter.user_activity_detected.connect(self.record_user_activity)
            self.global_event_filter.start_listening()
            logger.info("全局事件监听器已启动")
        except Exception as e:
            logger.error(f"启动全局事件监听器失败: {e}")
            
        if self.ui_initialized:
            # 显示课程
            self.display_lessons()
            
            # 检查小组件列表状态
            self.check_initial_widgets_state()
            
            # 根据小组件列表状态决定是否显示
            if self.has_valid_widgets:
                logger.info("检测到有效的小组件列表，准备显示主组件")
                # 更新UI宽度但不显示
                self.update_ui_width()
                # 使用淡入动画显示UI
                if self.ui_widget and not self.is_main_widget_visible:
                    logger.info("使用淡入动画显示主组件")
                    self.ui_widget.setWindowOpacity(0.0)
                    self.ui_widget.show()
                    self.fade_in_main_widget()
            else:
                logger.info("小组件列表为空或无效，等待update方法更新")
                # 设置UI为隐藏状态，等待update方法中的小组件列表更新
                if self.ui_widget:
                    self.ui_widget.hide()
                    self.is_main_widget_visible = False
                    
            logger.info("UI初始化完成")
        else:
            logger.error("UI未初始化，无法启动插件")
        
    def stop(self):
        """停止插件"""
        try:
            # 停止鼠标检测
            self.stop_mouse_detection()

            # 停止全局事件监听器
            if self.global_event_filter:
                self.global_event_filter.stop_listening()
                self.global_event_filter = None
                logger.info("全局事件监听器已停止")
            
            # 断开按钮信号连接
            if self.pushButton_switch:
                try:
                    self.pushButton_switch.clicked.disconnect()
                except:
                    pass
            if self.pushButton_light:
                try:
                    self.pushButton_light.clicked.disconnect()
                except:
                    pass
            if self.pushButton_dark:
                try:
                    self.pushButton_dark.clicked.disconnect()
                except:
                    pass
                
            # 停止进度条动画
            if self.blackboard_progress_animation:
                self.blackboard_progress_animation.stop()
                self.blackboard_progress_animation.deleteLater()
                self.blackboard_progress_animation = None
                
            if self.whiteboard_progress_animation:
                self.whiteboard_progress_animation.stop()
                self.whiteboard_progress_animation.deleteLater()
                self.whiteboard_progress_animation = None
                
            # 关闭熄屏模式
            if self.is_blackboard_mode and self.blackboard_widget:
                self.blackboard_widget.close()
                self.blackboard_widget.deleteLater()

            # 关闭白板模式
            if self.is_whiteboard_mode and self.whiteboard_widget:
                self.whiteboard_widget.close()
                self.whiteboard_widget.deleteLater()

            # 关闭提示窗口和相关动画
            self.close_tip_window()
            
            # 清理动画组
            if hasattr(self, 'tip_animation_group') and self.tip_animation_group:
                logger.info("停止提示窗口显示动画")
                self.tip_animation_group.stop()
                self.tip_animation_group.deleteLater()
                self.tip_animation_group = None
                
            if hasattr(self, 'tip_close_animation_group') and self.tip_close_animation_group:
                logger.info("停止提示窗口关闭动画")
                self.tip_close_animation_group.stop()
                self.tip_close_animation_group.deleteLater()
                self.tip_close_animation_group = None
                
            if self.ui_widget:
                self.ui_widget.close()
            logger.info(f"{self.plugin_name} 已停止")

            # 停止主组件动画
            if self.main_widget_animation:
                self.main_widget_animation.stop()
                self.main_widget_animation.deleteLater()
                self.main_widget_animation = None
                
        except Exception as e:
            logger.error(f"停止插件时出错: {e}")
        
    def update(self, app_context: Dict[str, Any]):
        """更新方法，由主程序定期调用"""
        # 更新应用上下文
        self.app_contexts = app_context
        
        # 如果初始小组件检查还没完成，先进行检查
        if not self.initial_widget_check_done:
            self.check_initial_widgets_state()
        
        # 检测主题变化
        theme_changed = self.check_theme_change()
        
        # 如果主题变化且需要重新初始化UI，则跳过后续处理
        if theme_changed and not self.ui_initialized:
            logger.info("主题变化导致UI重新初始化，跳过本次更新")
            return
        
        # 如果UI未初始化，尝试重新初始化
        if not self.ui_initialized:
            logger.warning("UI未初始化，尝试重新初始化")
            was_initialized_before = False  # 记录之前是否已经初始化过
            self.init_ui()
            if not self.ui_initialized:
                logger.error("UI重新初始化失败，跳过更新")
                return
            else:
                # UI重新初始化成功，需要重新显示课程和检查小组件状态
                logger.info("UI重新初始化成功，重新设置课程和显示状态")
                
                # 重新显示课程
                self.display_lessons()
                
                # 重新检查小组件状态
                self.check_initial_widgets_state()
                
                # 如果有有效的小组件，显示主组件
                if self.has_valid_widgets:
                    logger.info("UI重新初始化后检测到有效小组件，准备显示主组件")
                    self.update_ui_width()
                    if not self.is_main_widget_visible:
                        logger.info("启动淡入动画显示重新初始化的UI")
                        self.fade_in_main_widget()
                else:
                    logger.info("UI重新初始化后没有有效小组件，保持隐藏")
        
        # 检查是否应该显示明日课程
        should_show_tomorrow = self.should_show_tomorrow_course()
        
        if should_show_tomorrow and not self.showing_tomorrow_courses:
            # 切换到显示明日课程
            logger.info("切换到显示明日课程")
            self.show_tomorrow_courses()
        elif not should_show_tomorrow and self.showing_tomorrow_courses:
            # 切换回显示今日课程
            logger.info("切换回显示今日课程")
            self.show_today_courses()
        
        # 检查课程数据是否变化（只在显示今日课程时）
        if not self.showing_tomorrow_courses:
            current_lessons = self.app_contexts.get('Current_Lessons', {})
            if current_lessons != self.previous_lessons:
                logger.debug("检测到课程数据变化，重新绘制UI")
                self.previous_lessons = current_lessons.copy()
                self.display_lessons()
        
        # 检查widget列表是否变化，只有变化时才更新
        if self.has_widgets_changed():
            logger.debug("检测到widget列表变化，已触发相应处理")
        
        # 更新当前课程高亮 - 这里会自动处理错误情况（只在显示今日课程时）
        if not self.showing_tomorrow_courses:
            self.update_current_course_highlight()
        
        # 更新熄屏模式当前课程高亮
        self.update_blackboard_current_course_highlight()

        # 更新熄屏模式倒计时
        self.update_blackboard_countdown()

        # 更新白板模式当前课程高亮
        self.update_whiteboard_current_course_highlight()

        # 更新白板模式倒计时
        self.update_whiteboard_countdown()
        
        # 处理自动化功能
        self.handle_automation()

    def check_initial_widgets_state(self):
        """检查初始小组件列表状态"""
        try:
            # 获取当前小组件列表
            base_directory = self.app_contexts.get('Base_Directory', '.')
            widget_config_path = os.path.join(base_directory, "config", "widget.json")
            
            if os.path.exists(widget_config_path):
                with open(widget_config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    current_widgets = config.get('widgets', [])
                    
                # 检查小组件列表是否有效
                if current_widgets and len(current_widgets) > 0:
                    self.has_valid_widgets = True
                    self.display_widgets = current_widgets
                    self.previous_widgets = current_widgets.copy()
                    logger.info(f"初始小组件列表有效，包含 {len(current_widgets)} 个组件")
                    
                    # 如果UI已经初始化但主组件不可见，且这是初始检查，则显示主组件
                    if self.ui_initialized and not self.is_main_widget_visible and not self.initial_widget_check_done:
                        logger.info("初始检查发现有效小组件且UI已初始化，准备显示主组件")
                        # 这里不直接显示，由调用方决定显示逻辑
                        
                else:
                    self.has_valid_widgets = False
                    logger.info("初始小组件列表为空")
            else:
                self.has_valid_widgets = False
                logger.warning("widget.json配置文件不存在")
                
            self.initial_widget_check_done = True
            logger.info(f"初始小组件检查完成，has_valid_widgets={self.has_valid_widgets}")
            
        except Exception as e:
            logger.error(f"检查初始小组件状态失败: {e}")
            self.has_valid_widgets = False
            self.initial_widget_check_done = True

    def should_show_tomorrow_course(self):
        """判断是否应该显示明日课程"""
        try:
            # 检查开关设置
            if self.tomorrow_course_settings.get('switch', 'False') != 'True':
                logger.debug("明日课程功能未启用")
                return False
            
            # 获取当前时间
            current_time_str = self.app_contexts.get('Current_Time', '00:00:00')
            current_time = datetime.strptime(current_time_str, '%H:%M:%S').time()
            
            # 获取起始时间限制
            start_time_limit_str = self.tomorrow_course_settings.get('start_time_limit', '20:00')
            start_time_limit = datetime.strptime(start_time_limit_str, '%H:%M').time()
            
            # 检查当前时间是否晚于起始时间限制
            if current_time < start_time_limit:
                logger.debug(f"当前时间 {current_time_str} 早于起始时间限制 {start_time_limit_str}")
                return False
            
            # 计算今日课程结束时间
            today_end_time = self.calculate_today_course_end_time()
            if not today_end_time:
                logger.debug("无法计算今日课程结束时间")
                return False
            
            # 计算距离今日课程结束的剩余时间（分钟）
            current_datetime = datetime.combine(datetime.today(), current_time)
            today_end_datetime = datetime.combine(datetime.today(), today_end_time)
            
            if current_datetime >= today_end_datetime:
                # 当前时间已经超过今日课程结束时间
                time_remaining = 0
            else:
                time_remaining = (today_end_datetime - current_datetime).total_seconds() / 60
            
            # 获取设定的剩余时间阈值
            time_remaining_threshold = int(self.tomorrow_course_settings.get('time_remaining', '50'))
            
            logger.debug(f"距离今日课程结束剩余时间: {time_remaining:.1f} 分钟, 阈值: {time_remaining_threshold} 分钟")
            
            # 检查是否满足剩余时间条件
            if time_remaining > time_remaining_threshold:
                logger.debug("剩余时间未达到阈值，不显示明日课程")
                return False
            
            logger.info(f"满足明日课程显示条件: 剩余时间 {time_remaining:.1f} 分钟 <= 阈值 {time_remaining_threshold} 分钟")
            return True
            
        except Exception as e:
            logger.error(f"判断是否显示明日课程失败: {e}")
            return False

    def calculate_today_course_end_time(self):
        """计算今日课程结束时间"""
        try:
            # 获取时间线数据
            timeline_data = self.app_contexts.get('Timeline_Data', {})
            if not timeline_data:
                logger.warning("未获取到时间线数据")
                return None
            
            # 获取节点开始时间
            parts_start_time = self.app_contexts.get('Parts_Start_Time', [])
            if not parts_start_time:
                logger.warning("未获取到节点开始时间")
                return None
            
            # 找到最后一个节点
            last_part_index = len(parts_start_time) - 1
            last_part_start_time = parts_start_time[last_part_index]
            
            # 获取最后一个节点的所有活动
            last_part_activities = []
            for key, duration in timeline_data.items():
                if len(key) >= 2 and key[1] == str(last_part_index):
                    last_part_activities.append((key, int(duration)))
            
            if not last_part_activities:
                logger.warning(f"未找到最后一个节点 {last_part_index} 的活动数据")
                return None
            
            # 按照正确的顺序排序
            def activity_sort_key(item):
                activity_id = item[0]
                activity_number = activity_id[2] if len(activity_id) >= 3 else '0'
                activity_type = activity_id[0]
                return (int(activity_number) if activity_number.isdigit() else 0, activity_type)
            
            last_part_activities.sort(key=activity_sort_key)
            
            # 计算最后一个节点的结束时间
            current_time = last_part_start_time
            for activity_id, duration in last_part_activities:
                current_time += timedelta(minutes=duration)
            
            # 返回结束时间（只保留时间部分）
            return current_time.time()
            
        except Exception as e:
            logger.error(f"计算今日课程结束时间失败: {e}")
            return None

    def calculate_tomorrow_weekday(self):
        """计算明天的周次（0-6，0为周一，6为周日）"""
        try:
            current_weekday = self.app_contexts.get('Current_Week', 0)
            tomorrow_weekday = (current_weekday + 1) % 7
            logger.debug(f"当前周次: {current_weekday}, 明天周次: {tomorrow_weekday}")
            return tomorrow_weekday
        except Exception as e:
            logger.error(f"计算明天周次失败: {e}")
            return 0

    def calculate_tomorrow_parity(self):
        """计算明天是单周还是双周"""
        try:
            # 获取学期起始日期
            base_directory = self.app_contexts.get('Base_Directory', '.')
            config_path = os.path.join(base_directory, "config.ini")
            
            if not os.path.exists(config_path):
                logger.warning(f"config.ini文件不存在: {config_path}")
                return 'odd'  # 默认单周
            
            config = configparser.ConfigParser()
            config.read(config_path, encoding='utf-8')
            
            start_date_str = config.get('Date', 'start_date', fallback='2025-9-1')
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            
            # 计算明天的日期
            tomorrow_date = datetime.today().date() + timedelta(days=1)
            
            # 计算相差的天数
            days_diff = (tomorrow_date - start_date).days
            
            # 计算周数（从0开始）
            week_number = days_diff // 7
            
            # 判断单双周：奇数周为双周，偶数周为单周
            parity = 'even' if week_number % 2 == 1 else 'odd'
            
            logger.debug(f"明天日期: {tomorrow_date}, 起始日期: {start_date}, 相差天数: {days_diff}, 周数: {week_number}, 单双周: {parity}")
            
            return parity
            
        except Exception as e:
            logger.error(f"计算明天单双周失败: {e}")
            return 'odd'  # 默认单周

    def get_tomorrow_courses(self):
        """获取明日课程数据"""
        try:
            # 获取明天的周次和单双周
            tomorrow_weekday = self.calculate_tomorrow_weekday()
            tomorrow_parity = self.calculate_tomorrow_parity()
            
            # 获取课程数据
            loaded_data = self.app_contexts.get('Loaded_Data', {})
            if not loaded_data:
                logger.warning("未获取到课程数据")
                return {}
            
            # 获取课程表
            schedule_key = 'schedule_even' if tomorrow_parity == 'even' else 'schedule'
            schedule = loaded_data.get(schedule_key, {})
            
            # 获取对应周次的课程列表
            tomorrow_courses_list = schedule.get(str(tomorrow_weekday), [])
            if not tomorrow_courses_list:
                logger.warning(f"未找到周次 {tomorrow_weekday} 的课程数据")
                return {}
            
            # 获取时间线数据
            timeline = loaded_data.get('timeline', {})
            tomorrow_timeline = timeline.get(str(tomorrow_weekday), {})
            if not tomorrow_timeline:
                # 使用默认时间线
                tomorrow_timeline = timeline.get('default', {})
            
            # 提取课程活动（以'a'开头的键）
            course_activities = []
            for key in sorted(tomorrow_timeline.keys()):
                if key.startswith('a'):
                    course_activities.append(key)
            
            # 计算每个节点的课程数量
            node_course_counts = {}
            for activity in course_activities:
                if len(activity) >= 2:
                    node = activity[1]
                    node_course_counts[node] = node_course_counts.get(node, 0) + 1
            
            # 构建课程字典
            tomorrow_courses = {}
            course_index = 0
            
            for node in sorted(node_course_counts.keys()):
                node_course_count = node_course_counts[node]
                for i in range(node_course_count):
                    if course_index < len(tomorrow_courses_list):
                        course_name = tomorrow_courses_list[course_index]
                        # 生成课程ID（格式：a{节点序号}{课程序号}）
                        course_id = f"a{node}{i+1:02d}" if i+1 < 10 else f"a{node}{i+1}"
                        tomorrow_courses[course_id] = course_name
                        course_index += 1
                    else:
                        # 课程列表不足，用"暂无课程"补全
                        course_id = f"a{node}{i+1:02d}" if i+1 < 10 else f"a{node}{i+1}"
                        tomorrow_courses[course_id] = "暂无课程"
            
            logger.info(f"获取到明日课程: {tomorrow_courses}")
            return tomorrow_courses
            
        except Exception as e:
            logger.error(f"获取明日课程失败: {e}")
            return {}

    def show_tomorrow_courses(self):
        """显示明日课程"""
        try:
            if not self.ui_initialized or not self.ui_widget:
                logger.error("UI未初始化，无法显示明日课程")
                return
            
            # 获取明日课程数据
            tomorrow_courses = self.get_tomorrow_courses()
            if not tomorrow_courses:
                logger.warning("未获取到明日课程数据")
                return
            
            # 显示明日课程相关控件
            if self.tomorrow_course_text_label:
                self.tomorrow_course_text_label.setVisible(True)
            
            horizontal_spacer_fixed_left_2 = self.ui_widget.findChild(QObject, "horizontalSpacer_fixed_left_2")
            if horizontal_spacer_fixed_left_2:
                horizontal_spacer_fixed_left_2.setVisible(True)
            
            # 添加明日课程图标
            self.add_tomorrow_course_icon()
            
            # 清空现有课程布局
            self.clear_lesson_layout()
            
            # 按时间段分组明日课程
            lesson_groups = self.group_lessons_by_period(tomorrow_courses)
            logger.info(f"分组后的明日课程: {lesson_groups}")
            
            # 动态创建明日课程显示
            group_count = len(lesson_groups)
            for i, (period, lessons) in enumerate(lesson_groups.items()):
                # 获取这个时间段的所有课程ID
                period_course_ids = [key for key in tomorrow_courses.keys() if key[1] == period]
                
                # 添加本组的课程
                for j, (course_id, abbreviation) in enumerate(zip(period_course_ids, lessons)):
                    frame = self.create_lesson_frame(abbreviation, course_id)
                    if frame:
                        self.lesson_layout.addWidget(frame)
                        # 存储课程框架引用（但不用于高亮）
                        self.course_frames[course_id] = frame
                        logger.debug(f"添加明日课程框架: {abbreviation} (ID: {course_id})")
                    
                    # 课程之间添加2px间隔（最后一个课程后不添加）- 明日课程使用2px间隔
                    if j < len(lessons) - 1:
                        spacer = self.create_spacer(0)  # 明日课程使用2px间隔
                        if spacer:
                            self.lesson_layout.addItem(spacer)
                
                # 组之间添加分隔线（最后一组后不添加）
                if i < group_count - 1:
                    # 添加10px间隔
                    spacer_before = self.create_spacer(5)
                    if spacer_before:
                        self.lesson_layout.addItem(spacer_before)
                    
                    # 添加分隔线
                    divider = self.create_divider()
                    if divider:
                        self.lesson_layout.addWidget(divider)
                    
                    # 添加10px间隔
                    spacer_after = self.create_spacer(5)
                    if spacer_after:
                        self.lesson_layout.addItem(spacer_after)
            
            # 更新状态
            self.showing_tomorrow_courses = True
            logger.info("明日课程显示完成")
            
        except Exception as e:
            logger.error(f"显示明日课程失败: {e}")

    def show_today_courses(self):
        """显示今日课程"""
        try:
            if not self.ui_initialized or not self.ui_widget:
                logger.error("UI未初始化，无法显示今日课程")
                return
            
            # 隐藏明日课程相关控件
            if self.tomorrow_course_text_label:
                self.tomorrow_course_text_label.setVisible(False)
            
            horizontal_spacer_fixed_left_2 = self.ui_widget.findChild(QObject, "horizontalSpacer_fixed_left_2")
            if horizontal_spacer_fixed_left_2:
                horizontal_spacer_fixed_left_2.setVisible(False)
            
            # 移除明日课程图标
            self.remove_tomorrow_course_icon()
            
            # 重新显示今日课程
            self.display_lessons()
            
            # 更新状态
            self.showing_tomorrow_courses = False
            logger.info("切换回显示今日课程")
            
        except Exception as e:
            logger.error(f"显示今日课程失败: {e}")

    def add_tomorrow_course_icon(self):
        """添加明日课程图标"""
        try:
            # 如果已经存在图标，先移除
            self.remove_tomorrow_course_icon()
            
            # 获取图标路径
            base_directory = self.app_contexts.get('Base_Directory', '.')
            if self.current_theme_dark:
                icon_path = os.path.join(base_directory, "plugins", "cw-lessons-displayer", "ui", "img", "dark", "next.svg")
            else:
                icon_path = os.path.join(base_directory, "plugins", "cw-lessons-displayer", "ui", "img", "next.svg")
            
            if not os.path.exists(icon_path):
                logger.warning(f"明日课程图标不存在: {icon_path}")
                return
            
            # 创建图标标签
            self.tomorrow_course_icon_label = QLabel()
            self.tomorrow_course_icon_label.setFixedSize(24, 24)
            pixmap = QPixmap(icon_path)
            self.tomorrow_course_icon_label.setPixmap(pixmap)
            self.tomorrow_course_icon_label.setScaledContents(True)
            
            # 获取水平布局
            horizontal_layout = self.ui_widget.findChild(QHBoxLayout, "horizontalLayout")
            if not horizontal_layout:
                logger.error("未找到水平布局")
                return
            
            # 找到明日课程文本标签的位置
            tomorrow_course_text_index = -1
            for i in range(horizontal_layout.count()):
                item = horizontal_layout.itemAt(i)
                if item.widget() == self.tomorrow_course_text_label:
                    tomorrow_course_text_index = i
                    break
            
            if tomorrow_course_text_index == -1:
                logger.error("未找到明日课程文本标签")
                return
            
            # 在文本标签前插入图标
            horizontal_layout.insertWidget(tomorrow_course_text_index, self.tomorrow_course_icon_label)
            
            # 添加8px间隔（在图标和文本标签之间）
            spacer_8px = self.create_spacer(6)
            if spacer_8px:
                horizontal_layout.insertItem(tomorrow_course_text_index + 1, spacer_8px)
                # 保存间隔引用以便后续移除
                self.tomorrow_course_spacer = spacer_8px
            
            logger.debug("明日课程图标和间隔添加完成")
            
        except Exception as e:
            logger.error(f"添加明日课程图标失败: {e}")

    def remove_tomorrow_course_icon(self):
        """移除明日课程图标和间隔"""
        try:
            # 获取水平布局
            horizontal_layout = self.ui_widget.findChild(QHBoxLayout, "horizontalLayout")
            if not horizontal_layout:
                return
            
            # 移除图标
            if self.tomorrow_course_icon_label:
                horizontal_layout.removeWidget(self.tomorrow_course_icon_label)
                self.tomorrow_course_icon_label.deleteLater()
                self.tomorrow_course_icon_label = None
            
            # 移除间隔
            if self.tomorrow_course_spacer:
                # 找到间隔的位置并移除
                for i in range(horizontal_layout.count()):
                    item = horizontal_layout.itemAt(i)
                    if item == self.tomorrow_course_spacer:
                        horizontal_layout.removeItem(item)
                        break
                self.tomorrow_course_spacer = None
            
            logger.debug("明日课程图标和间隔已移除")
            
        except Exception as e:
            logger.error(f"移除明日课程图标失败: {e}")

    def handle_automation(self):
        """处理自动化模式切换"""
        try:
            # 直接获取当前课程名称，而不是通过current_course_id计算
            self.current_lesson_name = self.app_contexts.get('Current_Lesson')
            
            # 如果当前课程名称为空，尝试备用方法
            if not self.current_lesson_name:
                current_course_id = self.calculate_current_course()
                if current_course_id:
                    current_lessons = self.app_contexts.get('Current_Lessons', {})
                    self.current_lesson_name = current_lessons.get(current_course_id)
            
            # 检查课程是否变化
            if self.current_lesson_name != self.previous_lesson_name:
                self.on_lesson_changed()
            
            # 检查是否需要触发自动化
            self.check_automation_trigger()
            
        except Exception as e:
            logger.error(f"处理自动化失败: {e}")
    
    def on_lesson_changed(self):
        """当课程变化时调用"""
        logger.info(f"课程变化检测: {self.previous_lesson_name} -> {self.current_lesson_name}")
        
        # 重置自动化状态
        self.lesson_start_time = time.time()
        self.user_activity_detected = False
        self.automation_triggered = False
        
        # 停止之前的计时器
        if self.automation_timer:
            self.automation_timer.stop()
            self.automation_timer = None
            
        # 关闭提示窗口
        if self.tip_window:
            self.close_tip_window()
        
        # 检查新课程是否有自动化设置
        if self.current_lesson_name in self.automation_settings:
            settings = self.automation_settings[self.current_lesson_name]
            logger.info(f"新课程 '{self.current_lesson_name}' 有自动化设置: time={settings.get('time')}, "
                    f"click={settings.get('click')}, mode={settings.get('mode')}")
        else:
            logger.info(f"新课程 '{self.current_lesson_name}' 无自动化设置")
        
        # 更新课程名称
        self.previous_lesson_name = self.current_lesson_name
    
    def check_automation_trigger(self):
        """检查是否需要触发自动化"""
        if not self.current_lesson_name:
            logger.debug("当前课程名称为空，跳过自动化检查")
            return
            
        if self.automation_triggered:
            ## logger.debug(f"课程 '{self.current_lesson_name}' 的自动化已触发，跳过检查")
            return
            
        # 获取当前课程的设置
        lesson_settings = self.automation_settings.get(self.current_lesson_name)
        if not lesson_settings:
            ## logger.debug(f"课程 '{self.current_lesson_name}' 无自动化设置")
            return
            
        trigger_time = lesson_settings.get('time', 0)
        click_required = lesson_settings.get('click', 'False') == 'True'
        target_mode = lesson_settings.get('mode', 'none')
        
        logger.debug(f"检查自动化触发条件 - 课程: {self.current_lesson_name}, "
                    f"触发时间: {trigger_time}, 要求点击: {click_required}, 目标模式: {target_mode}")
        
        # 检查当前是否已经处于目标状态
        current_mode = self.get_current_mode()
        if current_mode == target_mode:
            logger.debug(f"当前已经处于目标模式 '{target_mode}'，跳过自动化触发")
            self.automation_triggered = True  # 标记为已触发，避免重复检查
            return
        
        # 获取当前活动时间信息
        time_info = self.get_current_activity_time_info()
        if not time_info:
            logger.debug("无法获取当前活动时间信息，跳过自动化检查")
            return
            
        total_seconds, remaining_seconds, activity_id, state = time_info
        
        # 计算已经过去的时间
        if self.lesson_start_time:
            elapsed_time = time.time() - self.lesson_start_time
        else:
            elapsed_time = 0
            
        logger.debug(f"时间信息 - 总时长: {total_seconds}秒, 剩余: {remaining_seconds}秒, "
                    f"已过去: {elapsed_time:.1f}秒, 活动ID: {activity_id}, 状态: {state}")
        
        # 检查是否到达触发时间
        should_trigger = False
        trigger_reason = ""
        
        if trigger_time > 0:  # 正数：持续时间
            if elapsed_time >= trigger_time:
                should_trigger = True
                trigger_reason = f"持续时间达到 {trigger_time} 秒 (实际: {elapsed_time:.1f} 秒)"
        else:  # 负数：剩余时间
            if remaining_seconds <= abs(trigger_time):
                should_trigger = True
                trigger_reason = f"剩余时间达到 {abs(trigger_time)} 秒 (实际: {remaining_seconds} 秒)"
        
        logger.debug(f"自动化触发检查结果: {should_trigger} - {trigger_reason}")
        
        if should_trigger:
            # 检查用户操作要求
            if not click_required and self.user_activity_detected:
                logger.info(f"课程 '{self.current_lesson_name}' 自动化被用户操作打断 (click_required=False)")
                self.automation_triggered = True
                return
                
            # 触发自动化
            logger.info(f"触发课程 '{self.current_lesson_name}' 的自动化: {trigger_reason}")
            self.trigger_automation(target_mode)
            self.automation_triggered = True

    def get_current_mode(self):
        """获取当前模式状态"""
        if self.is_blackboard_mode:
            return 'blackboard'
        elif self.is_whiteboard_mode:
            return 'whiteboard'
        else:
            return 'none'
    
    def trigger_automation(self, target_mode):
        """触发自动化模式切换"""
        try:
            # 再次检查当前是否已经处于目标状态（双重保险）
            current_mode = self.get_current_mode()
            if current_mode == target_mode:
                logger.info(f"当前已经处于目标模式 '{target_mode}'，无需切换")
                return
                
            logger.info(f"开始执行自动化模式切换: {target_mode}")
            
            # 显示提示窗口，传递 target_mode 参数
            if target_mode == 'blackboard':
                message = "即将切换至熄屏模式，按任意键打断"
            elif target_mode == 'whiteboard':
                message = "即将切换至白板模式，按任意键打断"
            else:  # none
                message = "即将关闭特殊模式，按任意键打断"
                
            logger.info(f"显示提示窗口: {message}")
            self.show_tip_window(message, target_mode)  # 传递 target_mode 参数
            
            logger.info("已启动5秒等待计时器，等待用户操作")
            
        except Exception as e:
            logger.error(f"触发自动化失败: {e}")
    
    def on_tip_timeout(self):
        """提示窗口超时处理（5秒后没有用户操作）"""
        try:
            logger.info("5秒等待计时器超时，检查用户操作状态")
            
            # 停止实时监测计时器
            if self.realtime_check_timer:
                self.realtime_check_timer.stop()
                self.realtime_check_timer = None
            
            # 检查用户是否在5秒内有操作
            if self.user_activity_detected:
                # 用户有操作，但实时监测可能没有及时处理，这里确保处理
                logger.info("检测到用户操作，自动化被打断")
                self.handle_immediate_interruption()
            else:
                # 用户无操作，执行模式切换
                logger.info("未检测到用户操作，执行自动化模式切换")
                self.execute_mode_switch(self.current_automation_mode)  # 使用实例变量
                # 立即关闭提示窗口（带动画）
                self.close_tip_window()
                
        except Exception as e:
            logger.error(f"处理提示超时失败: {e}")
    
    def execute_mode_switch(self, mode):
        """执行模式切换"""
        try:
            logger.info(f"开始执行模式切换: {mode}")
            
            current_blackboard = self.is_blackboard_mode
            current_whiteboard = self.is_whiteboard_mode
            
            if mode == 'blackboard':
                if not self.is_blackboard_mode:
                    logger.info("切换到熄屏模式")
                    self.show_blackboard()
                else:
                    logger.info("已在熄屏模式，无需切换")
            elif mode == 'whiteboard':
                if not self.is_whiteboard_mode:
                    logger.info("切换到白板模式")
                    self.show_whiteboard()
                else:
                    logger.info("已在白板模式，无需切换")
            else:  # none
                logger.info("关闭特殊模式")
                if self.is_blackboard_mode:
                    logger.info("关闭熄屏模式")
                    self.close_blackboard()
                if self.is_whiteboard_mode:
                    logger.info("关闭白板模式")
                    self.close_whiteboard()
                    
            logger.info(f"模式切换完成: 熄屏模式 {current_blackboard}->{self.is_blackboard_mode}, "
                    f"白板模式 {current_whiteboard}->{self.is_whiteboard_mode}")
                        
        except Exception as e:
            logger.error(f"执行模式切换失败: {e}")
    
    def show_tip_window(self, message, mode):
        """显示提示窗口（带淡入动画）
        Args:
            message: 提示消息
            mode: 自动化模式 ('blackboard', 'whiteboard', 'none')
        """
        try:
            from PyQt5 import uic
            from PyQt5.QtCore import QPropertyAnimation, QEasingCurve, QPoint, QParallelAnimationGroup
            
            logger.info(f"开始显示提示窗口: {message}, 模式: {mode}")
            
            # 先关闭可能存在的提示窗口
            self.close_tip_window()
            
            # 重置用户操作状态
            self.reset_user_activity_state()
            
            # 保存当前模式到实例变量，供其他方法使用
            self.current_automation_mode = mode
            
            # 获取UI文件路径
            base_directory = self.app_contexts.get('Base_Directory', '.')
            ui_file_path = os.path.join(base_directory, "plugins", "cw-lessons-displayer", "ui", "tips.ui")
            
            logger.info(f"加载提示窗口UI文件: {ui_file_path}")
            
            if not os.path.exists(ui_file_path):
                logger.error(f"提示窗口UI文件不存在: {ui_file_path}")
                return
                
            # 加载UI文件
            self.tip_window = uic.loadUi(ui_file_path)
            
            if not self.tip_window:
                logger.error("提示窗口加载失败，返回None")
                return
                
            logger.info("提示窗口UI加载成功")
            
            # 设置窗口属性
            self.tip_window.setWindowFlags(
                Qt.FramelessWindowHint | 
                Qt.WindowStaysOnTopHint |
                Qt.Tool
            )
            self.tip_window.setAttribute(Qt.WA_TranslucentBackground)
            self.tip_window.setAttribute(Qt.WA_ShowWithoutActivating)
            
            # 更新文本
            self.update_tip_text(message)
            
            # 获取屏幕尺寸
            screen = QApplication.primaryScreen().availableGeometry()
            screen_width = screen.width()
            
            # 计算初始位置（水平居中，距顶部150px）
            x = (screen_width - self.tip_window.width()) // 2
            initial_y = 150  # 初始位置：距顶部150px
            target_y = 200   # 目标位置：距顶部200px
            
            logger.info(f"窗口位置 - 初始: ({x}, {initial_y}), 目标: ({x}, {target_y})")
            
            # 设置初始位置和透明度
            self.tip_window.move(x, initial_y)
            self.tip_window.setWindowOpacity(0.0)
            
            # 显示窗口
            self.tip_window.show()
            logger.info("提示窗口已显示，准备开始动画")
            
            # 创建并行动画组
            self.tip_animation_group = QParallelAnimationGroup()
            
            # 透明度动画：从0到1
            opacity_animation = QPropertyAnimation(self.tip_window, b"windowOpacity")
            opacity_animation.setDuration(300)
            opacity_animation.setStartValue(0.0)
            opacity_animation.setEndValue(1.0)
            opacity_animation.setEasingCurve(QEasingCurve.OutCubic)
            
            # 位置动画：从150px移动到200px
            position_animation = QPropertyAnimation(self.tip_window, b"pos")
            position_animation.setDuration(300)
            position_animation.setStartValue(QPoint(x, initial_y))
            position_animation.setEndValue(QPoint(x, target_y))
            position_animation.setEasingCurve(QEasingCurve.OutCubic)
            
            # 添加动画到动画组
            self.tip_animation_group.addAnimation(opacity_animation)
            self.tip_animation_group.addAnimation(position_animation)
            
            # 连接动画完成信号
            self.tip_animation_group.finished.connect(self._on_tip_show_animation_finished)
            
            # 开始动画
            self.tip_animation_group.start()
            
            logger.info("提示窗口淡入动画已启动")
            
            # 启动实时监测定时器（每20毫秒检查一次用户操作）
            self.realtime_check_timer = QTimer()
            self.realtime_check_timer.timeout.connect(self.check_realtime_user_activity)
            self.realtime_check_timer.start(20)  # 每20毫秒检查一次
            
            # 设置5秒计时器（备用，用于超时处理）
            self.tip_timer = QTimer()
            self.tip_timer.setSingleShot(True)
            self.tip_timer.timeout.connect(self.on_tip_timeout)
            self.tip_timer.start(5000)  # 5秒
            
            logger.info("已启动实时监测计时器和5秒备用计时器")
            
        except Exception as e:
            logger.error(f"显示提示窗口失败: {e}", exc_info=True)

    def check_realtime_user_activity(self):
        """实时监测用户操作，一旦检测到立即打断"""
        try:
            if not self.tip_window or not self.tip_window.isVisible():
                # 提示窗口已关闭，停止监测
                if self.realtime_check_timer:
                    self.realtime_check_timer.stop()
                    self.realtime_check_timer = None
                return
            
            # 检查用户是否有操作
            if self.user_activity_detected:
                logger.info("实时监测到用户操作，立即打断自动化")
                self.handle_immediate_interruption()
                
        except Exception as e:
            logger.error(f"实时监测用户操作失败: {e}")

    def handle_immediate_interruption(self):
        """处理立即打断"""
        try:
            # 停止所有计时器
            if self.realtime_check_timer:
                self.realtime_check_timer.stop()
                self.realtime_check_timer = None
                
            if self.tip_timer:
                self.tip_timer.stop()
                self.tip_timer = None
            
            # 关闭当前提示窗口（带动画）
            self.close_tip_window()
            
            # 短暂延迟后显示打断成功提示
            QTimer.singleShot(300, self.show_interruption_success)
            
        except Exception as e:
            logger.error(f"处理立即打断失败: {e}")

    def show_interruption_success(self):
        """显示打断成功提示"""
        try:
            logger.info("显示打断成功提示")
            
            # 使用相同的提示窗口显示打断成功消息
            # 注意：这里不需要传递 mode 参数，因为只是显示打断成功
            self.show_tip_window("已成功打断", "none")
            
            # 2秒后自动关闭
            QTimer.singleShot(3000, self.close_tip_window)
            
        except Exception as e:
            logger.error(f"显示打断成功提示失败: {e}")
    
    def update_tip_text(self, message):
        """更新提示文本"""
        if not self.tip_window:
            logger.warning("提示窗口不存在，无法更新文本")
            return
            
        # 查找文本标签
        tip_text = self.tip_window.findChild(QLabel, "next_lesson_text_4")
        if tip_text:
            tip_text.setText(message)
            
            # 调整窗口宽度以适应文本
            font_metrics = tip_text.fontMetrics()
            text_width = font_metrics.horizontalAdvance(message) + 50  # 加上边距
            self.tip_window.setFixedWidth(min(text_width, 600))  # 限制最大宽度
            
            logger.debug(f"更新提示文本: {message}, 窗口宽度调整为: {self.tip_window.width()}px")
            
            # 如果窗口正在显示，重新居中并保持当前位置的y坐标
            if self.tip_window.isVisible():
                screen = QApplication.primaryScreen().availableGeometry()
                x = (screen.width() - self.tip_window.width()) // 2
                current_y = self.tip_window.y()  # 保持当前的y坐标
                self.tip_window.move(x, current_y)
                logger.debug(f"窗口重新居中: ({x}, {current_y})")
        else:
            logger.warning("未找到提示文本标签")
    
    def close_tip_window(self):
        """关闭提示窗口（带淡出动画）"""
        try:
            # 停止实时监测计时器
            if hasattr(self, 'realtime_check_timer') and self.realtime_check_timer:
                self.realtime_check_timer.stop()
                self.realtime_check_timer = None

            # 如果窗口不存在，直接返回
            if not self.tip_window:
                logger.debug("提示窗口不存在，无需关闭")
                # 确保计时器也被停止
                if self.tip_timer:
                    self.tip_timer.stop()
                    self.tip_timer = None
                return
                
            logger.info("开始关闭提示窗口动画")
            
            # 如果正在执行淡入动画，先停止
            if self.tip_animation_group and self.tip_animation_group.state() == self.tip_animation_group.Running:
                logger.info("停止正在进行的显示动画")
                self.tip_animation_group.stop()
                if self.tip_animation_group:
                    self.tip_animation_group.deleteLater()
                    self.tip_animation_group = None
            
            from PyQt5.QtCore import QPropertyAnimation, QEasingCurve, QPoint, QParallelAnimationGroup
            
            # 获取当前窗口位置和目标位置
            current_pos = self.tip_window.pos()
            target_y = 150  # 目标位置：距顶部150px
            
            logger.info(f"关闭动画 - 当前位置: ({current_pos.x()}, {current_pos.y()}), 目标位置: ({current_pos.x()}, {target_y})")
            
            # 创建并行动画组
            self.tip_close_animation_group = QParallelAnimationGroup()
            
            # 透明度动画：从当前透明度到0
            current_opacity = self.tip_window.windowOpacity()
            opacity_animation = QPropertyAnimation(self.tip_window, b"windowOpacity")
            opacity_animation.setDuration(300)
            opacity_animation.setStartValue(current_opacity)
            opacity_animation.setEndValue(0.0)
            opacity_animation.setEasingCurve(QEasingCurve.InCubic)
            
            # 位置动画：从当前位置移动到距顶部100px
            position_animation = QPropertyAnimation(self.tip_window, b"pos")
            position_animation.setDuration(300)
            position_animation.setStartValue(current_pos)
            position_animation.setEndValue(QPoint(current_pos.x(), target_y))
            position_animation.setEasingCurve(QEasingCurve.InCubic)
            
            # 添加动画到动画组
            self.tip_close_animation_group.addAnimation(opacity_animation)
            self.tip_close_animation_group.addAnimation(position_animation)
            
            # 动画结束后真正关闭窗口
            self.tip_close_animation_group.finished.connect(self._finish_close_tip_window)
            
            # 开始动画
            self.tip_close_animation_group.start()
            
            logger.info("提示窗口淡出动画已启动")
            
        except Exception as e:
            logger.error(f"关闭提示窗口失败: {e}", exc_info=True)
            # 如果动画失败，直接关闭窗口
            self._finish_close_tip_window()

    def _finish_close_tip_window(self):
        """真正关闭提示窗口（动画结束后调用）"""
        try:
            logger.info("开始最终关闭提示窗口")
            
            # 清理自动化模式
            self.current_automation_mode = None
            
            # 确保停止实时监测计时器
            if self.realtime_check_timer:
                logger.info("停止实时监测计时器")
                self.realtime_check_timer.stop()
                self.realtime_check_timer = None
                
            if self.tip_window:
                logger.info("关闭提示窗口对象")
                self.tip_window.close()
                self.tip_window.deleteLater()
                self.tip_window = None
            else:
                logger.info("提示窗口已不存在")
                
            # 清理动画组
            if self.tip_animation_group:
                logger.info("清理显示动画组")
                self.tip_animation_group.deleteLater()
                self.tip_animation_group = None
                
            if self.tip_close_animation_group:
                logger.info("清理关闭动画组")
                self.tip_close_animation_group.deleteLater()
                self.tip_close_animation_group = None
                
            # 停止计时器
            if self.tip_timer:
                logger.info("停止提示计时器")
                self.tip_timer.stop()
                self.tip_timer = None
                
            logger.info("提示窗口已完全关闭")
            
        except Exception as e:
            logger.error(f"最终关闭提示窗口失败: {e}", exc_info=True)

    def _on_tip_show_animation_finished(self):
        """提示窗口显示动画完成回调"""
        logger.info("提示窗口显示动画完成")
        
        # 清理动画组
        if self.tip_animation_group:
            self.tip_animation_group.deleteLater()
            self.tip_animation_group = None
    
    def record_user_activity(self):
        """记录用户操作"""
        if not self.user_activity_detected:
            self.user_activity_detected = True
            current_time = time.strftime('%H:%M:%S')
            logger.info(f"检测到用户操作，设置 user_activity_detected=True (时间: {current_time})")
            
            # 如果有正在等待的自动化，记录日志（实时监测会立即处理）
            if hasattr(self, 'tip_timer') and self.tip_timer and self.tip_timer.isActive():
                logger.info("检测到用户操作，实时监测将立即处理打断")
    
    def eventFilter(self, obj, event):
        """事件过滤器，用于检测用户操作"""
        event_type = event.type()
        
        # 检测鼠标点击、键盘按下、鼠标移动等操作
        if event_type in [event.MouseButtonPress, event.MouseButtonRelease, 
                         event.KeyPress, event.KeyRelease, event.MouseMove]:
            self.record_user_activity()
            
        return False  # 继续正常事件处理

    def reset_user_activity_state(self):
        """重置用户操作状态，用于提示窗口显示时"""
        self.user_activity_detected = False
        logger.info("重置用户操作状态，开始监测5秒内的操作")
                
    def has_widgets_changed(self):
        """检查widget列表是否发生变化，并处理从无到有的情况"""
        try:
            base_directory = self.app_contexts.get('Base_Directory', '.')
            widget_config_path = os.path.join(base_directory, "config", "widget.json")
            
            if os.path.exists(widget_config_path):
                with open(widget_config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    current_widgets = config.get('widgets', [])
                    
                # 检查是否从无小组件变为有小组件
                previous_was_empty = not self.has_valid_widgets
                current_is_empty = len(current_widgets) == 0
                
                # 如果之前没有有效小组件，现在有了，触发显示
                if previous_was_empty and not current_is_empty:
                    logger.info(f"检测到小组件列表从空变为非空，准备显示主组件。widget数量: {len(current_widgets)}")
                    self.has_valid_widgets = True
                    self.display_widgets = current_widgets
                    self.previous_widgets = current_widgets.copy()
                    
                    # 更新UI宽度并淡入显示
                    self.update_ui_width()
                    self.fade_in_main_widget()
                    return True
                    
                # 如果之前有小组件，现在变空了，触发隐藏
                elif not previous_was_empty and current_is_empty:
                    logger.info("检测到小组件列表从非空变为空，隐藏主组件")
                    self.has_valid_widgets = False
                    self.fade_out_main_widget()
                    return True
                    
                # 比较当前列表和上一次列表（常规变化）
                if current_widgets != self.previous_widgets:
                    self.previous_widgets = current_widgets.copy()
                    self.display_widgets = current_widgets
                    
                    # 只有当我们有有效小组件时才处理常规变化
                    if self.has_valid_widgets:
                        # 根据主组件当前状态决定更新方式
                        if self.is_main_widget_visible:
                            # 如果主组件当前可见，先淡出，然后在淡出完成后更新宽度并淡入
                            logger.info(f"检测到widget列表变化，启动淡出-更新-淡入流程。widget数量: {len(current_widgets)}")
                            self.pending_width_update = True
                            self.fade_out_main_widget()
                        else:
                            # 如果主组件不可见，直接更新宽度并淡入
                            logger.info(f"检测到widget列表变化，直接更新宽度并淡入。widget数量: {len(current_widgets)}")
                            self.update_ui_width()
                            self.fade_in_main_widget()
                        
                        return True
                        
            else:
                # 配置文件不存在，视为没有有效小组件
                if self.has_valid_widgets:
                    logger.info("widget.json配置文件不存在，隐藏主组件")
                    self.has_valid_widgets = False
                    self.fade_out_main_widget()
                    return True
                    
        except Exception as e:
            logger.error(f"检查widget变化失败: {e}")
            
        return False
            
    def update_ui_width(self):
        """更新UI宽度"""
        try:
            # 检查UI部件是否已初始化
            if not self.ui_initialized or self.ui_widget is None:
                logger.warning("UI部件未正确初始化，无法更新宽度")
                return
            
            # 只有在有有效小组件时才更新宽度
            if not self.has_valid_widgets:
                logger.debug("没有有效的小组件列表，跳过宽度更新")
                return
            
            # 获取组件宽度字典
            self.widgets_width = self.app_contexts.get('Widgets_Width', {})
            
            # 计算总宽度
            self.calculate_total_width()
            
            # 设置主窗口宽度
            main_width = self.total_width
            self.ui_widget.setFixedWidth(main_width)
            
            # 设置位置
            self.update_position()
            
            # 确保UI显示（只有在有有效小组件时）
            if not self.ui_widget.isVisible() and self.has_valid_widgets:
                logger.debug("UI部件未显示，强制显示")
                self.ui_widget.show()
            
            logger.debug(f"组件总宽度: {self.total_width}px, UI宽度: {main_width}px")
            
        except Exception as e:
            logger.error(f"更新UI宽度失败: {e}")
                
    def update_position(self):
        """更新窗口位置"""
        try:
            if not self.ui_widget:
                return
                
            # 获取屏幕尺寸
            screen = QApplication.primaryScreen().availableGeometry()
            screen_width = screen.width()
            
            # 计算位置：水平居中，距顶部112px
            x = (screen_width - self.ui_widget.width()) // 2
            y = 112
            
            # 直接设置位置，不检查是否变化
            self.ui_widget.move(x, y)
            logger.debug(f"设置窗口位置: ({x}, {y})")
            
            # 确保窗口显示
            if not self.ui_widget.isVisible():
                self.ui_widget.show()
                logger.info("窗口未显示，强制显示")
            
        except Exception as e:
            logger.error(f"更新位置失败: {e}")
            
    def calculate_total_width(self):
        """计算总宽度"""
        self.total_width = 0
        
        if not self.display_widgets:
            logger.warning("显示组件列表为空")
            return
            
        # 累加每个组件的宽度
        for widget in self.display_widgets:
            if widget in self.widgets_width:
                widget_width = self.widgets_width[widget]
                self.total_width += widget_width
                ## logger.debug(f"组件 '{widget}' 宽度: {widget_width}px")
            else:
                logger.warning(f"未找到组件 '{widget}' 的宽度信息")
                
        # 加上组件间隔（每个组件14px）
        if len(self.display_widgets) > 1:
            spacing_width = (len(self.display_widgets) - 1) * 0 - 20
            self.total_width += spacing_width
            ## logger.debug(f"组件间隔宽度: {spacing_width}px")
        
        ## logger.info(f"计算总宽度: {self.total_width}px")

    def check_theme_change(self):
        """检测主题变化"""
        try:
            current_dark = isDarkTheme()
            if current_dark != self.current_theme_dark:
                logger.info(f"检测到主题变化: {'深色' if self.current_theme_dark else '浅色'} -> {'深色' if current_dark else '浅色'}")
                
                # 更新主题状态
                self.current_theme_dark = current_dark
                
                # 如果主组件当前可见，先淡出然后重新初始化UI并淡入
                if self.is_main_widget_visible:
                    logger.info("主题变化时主组件可见，启动淡出-重新初始化-淡入流程")
                    self.pending_width_update = True
                    self.fade_out_main_widget()
                else:
                    # 如果不可见，直接重新初始化
                    logger.info("主题变化时主组件不可见，直接重新初始化")
                    self.init_ui(theme_changed=True)
                    
                return True
            return False
        except Exception as e:
            logger.error(f"检测主题变化失败: {e}")
            return False

    def setup_button_events(self):
        """设置按钮事件"""
        try:
            # 换课按钮事件
            if self.pushButton_switch:
                self.pushButton_switch.clicked.connect(self.on_switch_clicked)
                logger.debug("设置换课按钮事件")
            
            # 白板模式按钮事件
            if self.pushButton_light:
                self.pushButton_light.clicked.connect(self.on_light_clicked)
                logger.debug("设置白板模式按钮事件")
            
            # 熄屏模式按钮事件
            if self.pushButton_dark:
                self.pushButton_dark.clicked.connect(self.on_dark_clicked)
                logger.debug("设置熄屏模式按钮事件")
                
        except Exception as e:
            logger.error(f"设置按钮事件失败: {e}")

    def setup_button_styles(self):
        """设置按钮悬停样式"""
        # 当前主题
        is_dark = isDarkTheme()

        try:
            if is_dark:
                # 基础样式
                base_style = """
                    QPushButton {
                        background-color: rgba(255, 255, 255, 30);
                        border: 1px solid;
                        border-color: rgba(255, 255, 255, 35);
                        border-top-color: rgba(255, 255, 255, 45);
                        border-radius: 17px;
                    }
                """

                # 悬停样式
                hover_style = """
                    QPushButton:hover {
                        background-color: rgba(255, 255, 255, 40);
                    }
                    QPushButton:pressed {
                        background-color: rgba(255, 255, 255, 20);
                        border-color: rgba(255, 255, 255, 15);
                        border-top-color: rgba(255, 255, 255, 25);
                    }
                """

            else:
                # 基础样式
                base_style = """
                    QPushButton {
                        background-color: rgb(255, 255, 255);
                        border: 1px solid;
                        border-color: rgba(0, 0, 0, 20);
                        border-bottom-color: rgba(0, 0, 0, 40);
                        border-radius: 17px;
                    }
                """
                
                # 悬停样式
                hover_style = """
                    QPushButton:hover {
                        background-color: rgba(250, 250, 250, 200);
                        border-color: rgba(0, 0, 0, 25);
                        border-bottom-color: rgba(0, 0, 0, 45);
                    }
                    QPushButton:pressed {
                        background-color: rgba(250, 250, 250, 140);
                        border-color: rgba(0, 0, 0, 25);
                        border-bottom-color: rgba(0, 0, 0, 45);
                    }
                """
            
            # 应用样式到所有按钮
            buttons = [self.pushButton_switch, self.pushButton_light, self.pushButton_dark]
            for button in buttons:
                if button:
                    # 获取按钮当前是否启用
                    is_enabled = button.isEnabled()
                    
                    # 如果按钮被禁用，使用不同的样式
                    if not is_enabled:
                        if is_dark:
                            disabled_style = """
                                QPushButton {
                                    background-color: rgba(255, 255, 255, 10);
                                    border: 1px solid;
                                    border-color: rgba(255, 255, 255, 15);
                                    border-top-color: rgba(255, 255, 255, 25);
                                    border-radius: 17px;
                                }
                            """
                        else:
                            disabled_style = """
                                QPushButton {
                                    background-color: rgba(0, 0, 0, 20);
                                    border: 1px solid;
                                    border-color: rgba(0, 0, 0, 15);
                                    border-bottom-color: rgba(0, 0, 0, 25);
                                    border-radius: 17px;
                                }
                            """
                        button.setStyleSheet(disabled_style)
                    else:
                        button.setStyleSheet(base_style + hover_style)
                        
            logger.debug("设置按钮悬停样式完成")
            
        except Exception as e:
            logger.error(f"设置按钮样式失败: {e}")

    def on_switch_clicked(self):
        """换课按钮点击事件"""
        try:
            logger.info("换课按钮被点击")
            # 在这里添加换课功能

        except Exception as e:
            logger.error(f"处理换课按钮点击事件失败: {e}")

    def on_light_clicked(self):
        """白板模式按钮点击事件"""
        try:
            logger.info("白板模式按钮被点击")
            # 切换到白板模式
            self.show_whiteboard()
            
        except Exception as e:
            logger.error(f"处理白板模式按钮点击事件失败: {e}")

    def on_dark_clicked(self):
        """熄屏模式按钮点击事件"""
        try:
            logger.info("熄屏模式按钮被点击")
            # 切换到熄屏模式
            self.show_blackboard()
            
        except Exception as e:
            logger.error(f"处理熄屏模式按钮点击事件失败: {e}")
    
    def init_blackboard_ui(self):
        """初始化熄屏模式UI"""
        try:
            from PyQt5 import uic
            from PyQt5.QtCore import QPropertyAnimation, QEasingCurve
            
            # 获取UI文件路径
            base_directory = self.app_contexts.get('Base_Directory', '.')
            ui_file_path = os.path.join(base_directory, "plugins", "cw-lessons-displayer", "ui", "blackboard.ui")
            
            logger.info(f"尝试加载熄屏模式UI文件: {ui_file_path}")
            
            if not os.path.exists(ui_file_path):
                logger.error(f"熄屏模式UI文件不存在: {ui_file_path}")
                return False
                
            # 如果之前已经有熄屏模式UI部件，先清理
            if self.blackboard_widget:
                self.blackboard_widget.deleteLater()
                self.blackboard_widget = None
                self.blackboard_lesson_layout = None
                self.blackboard_course_frames.clear()
                
            # 加载UI文件
            self.blackboard_widget = uic.loadUi(ui_file_path)
            
            if self.blackboard_widget is None:
                logger.error("熄屏模式UI文件加载失败，返回None")
                return False
                
            logger.info("熄屏模式UI文件加载成功")
            
            # 设置窗口属性 - 覆盖任务栏全屏
            self.blackboard_widget.setWindowFlags(
                Qt.FramelessWindowHint | 
                Qt.WindowStaysOnTopHint |  # 置顶显示
                Qt.Tool |
                Qt.CustomizeWindowHint  # 自定义窗口，避免系统边框
            )
            self.blackboard_widget.setAttribute(Qt.WA_TranslucentBackground)
            self.blackboard_widget.setAttribute(Qt.WA_ShowWithoutActivating)
            
            # 获取课程布局
            self.blackboard_lesson_layout = self.blackboard_widget.findChild(QHBoxLayout, "horizontalLayout_lesson_list")
            if not self.blackboard_lesson_layout:
                logger.error("未找到熄屏模式课程布局")
                return False
                
            logger.info("找到熄屏模式课程布局")
            
            # 获取关闭按钮并设置事件
            pushButton_close = self.blackboard_widget.findChild(QPushButton, "pushButton_close")
            if pushButton_close:
                pushButton_close.clicked.connect(self.close_blackboard)
                logger.debug("设置熄屏模式关闭按钮事件")
            
            # 获取白板模式按钮并设置事件
            pushButton_light = self.blackboard_widget.findChild(QPushButton, "pushButton_light")
            if pushButton_light:
                pushButton_light.clicked.connect(self.switch_to_whiteboard_from_blackboard)
                logger.debug("设置熄屏模式切换到白板模式按钮事件")
            
            # 设置关闭按钮样式（深色模式样式）
            self.setup_blackboard_button_styles()
            
            # 显示课程
            self.display_blackboard_lessons()
            
            # 初始化进度条动画
            self.init_blackboard_progress_animation()
    
            # 初始化鼠标检测
            self.init_mouse_detection()
            
            return True
            
        except Exception as e:
            logger.error(f"初始化熄屏模式UI失败: {e}")
            return False

    def init_whiteboard_ui(self):
        """初始化白板模式UI"""
        try:
            from PyQt5 import uic
            from PyQt5.QtCore import QPropertyAnimation, QEasingCurve
            
            # 获取UI文件路径
            base_directory = self.app_contexts.get('Base_Directory', '.')
            ui_file_path = os.path.join(base_directory, "plugins", "cw-lessons-displayer", "ui", "whiteboard.ui")
            
            logger.info(f"尝试加载白板模式UI文件: {ui_file_path}")
            
            if not os.path.exists(ui_file_path):
                logger.error(f"白板模式UI文件不存在: {ui_file_path}")
                return False
                
            # 如果之前已经有白板模式UI部件，先清理
            if self.whiteboard_widget:
                self.whiteboard_widget.deleteLater()
                self.whiteboard_widget = None
                self.whiteboard_lesson_layout = None
                self.whiteboard_course_frames.clear()
                
            # 加载UI文件
            self.whiteboard_widget = uic.loadUi(ui_file_path)
            
            if self.whiteboard_widget is None:
                logger.error("白板模式UI文件加载失败，返回None")
                return False
                
            logger.info("白板模式UI文件加载成功")
            
            # 设置窗口属性 - 覆盖任务栏全屏
            self.whiteboard_widget.setWindowFlags(
                Qt.FramelessWindowHint | 
                Qt.WindowStaysOnTopHint |  # 置顶显示
                Qt.Tool |
                Qt.CustomizeWindowHint  # 自定义窗口，避免系统边框
            )
            self.whiteboard_widget.setAttribute(Qt.WA_TranslucentBackground)
            self.whiteboard_widget.setAttribute(Qt.WA_ShowWithoutActivating)
            
            # 获取课程布局
            self.whiteboard_lesson_layout = self.whiteboard_widget.findChild(QHBoxLayout, "horizontalLayout_lesson_list")
            if not self.whiteboard_lesson_layout:
                logger.error("未找到白板模式课程布局")
                return False
                
            logger.info("找到白板模式课程布局")
            
            # 获取关闭按钮并设置事件
            pushButton_close = self.whiteboard_widget.findChild(QPushButton, "pushButton_close")
            if pushButton_close:
                pushButton_close.clicked.connect(self.close_whiteboard)
                logger.debug("设置白板模式关闭按钮事件")
            
            # 获取熄屏模式按钮并设置事件
            pushButton_dark = self.whiteboard_widget.findChild(QPushButton, "pushButton_dark")
            if pushButton_dark:
                pushButton_dark.clicked.connect(self.switch_to_blackboard_from_whiteboard)
                logger.debug("设置白板模式切换到熄屏模式按钮事件")
            
            # 设置按钮样式（浅色模式样式）
            self.setup_whiteboard_button_styles()
            
            # 显示课程
            self.display_whiteboard_lessons()
            
            # 初始化进度条动画
            self.init_whiteboard_progress_animation()

            # 初始化鼠标检测
            self.init_mouse_detection()
            
            return True
            
        except Exception as e:
            logger.error(f"初始化白板模式UI失败: {e}")
            return False

    def display_blackboard_lessons(self):
        """显示熄屏模式课程"""
        try:
            if not self.blackboard_lesson_layout:
                logger.error("熄屏模式课程布局未初始化")
                return
                
            # 获取当前课程
            current_lessons = self.app_contexts.get('Current_Lessons', {})
            if not current_lessons:
                logger.info("没有找到当前课程数据")
                return
                
            logger.info(f"获取到熄屏模式课程数据: {current_lessons}")
            
            # 清空课程框架字典和状态
            self.blackboard_course_frames.clear()
            self.blackboard_current_course_id = None
            self.blackboard_previous_highlight_id = None
            self.blackboard_current_state = None
            
            # 按时间段分组
            lesson_groups = self.group_lessons_by_period(current_lessons)
            logger.info(f"熄屏模式分组后的课程: {lesson_groups}")
            
            # 清空现有布局
            self.clear_blackboard_lesson_layout()
            
            # 动态创建课程显示
            group_count = len(lesson_groups)
            for i, (period, lessons) in enumerate(lesson_groups.items()):
                # 获取这个时间段的所有课程ID
                period_course_ids = [key for key in current_lessons.keys() if key[1] == period]
                
                # 添加本组的课程
                for j, (course_id, abbreviation) in enumerate(zip(period_course_ids, lessons)):
                    frame = self.create_blackboard_lesson_frame(abbreviation, course_id)
                    if frame:
                        self.blackboard_lesson_layout.addWidget(frame)
                        # 存储课程框架引用
                        self.blackboard_course_frames[course_id] = frame
                        logger.debug(f"添加熄屏模式课程框架: {abbreviation} (ID: {course_id})")
                    
                    # 课程之间添加6px间隔（最后一个课程后不添加）
                    if j < len(lessons) - 1:
                        spacer = self.create_spacer(6)
                        if spacer:
                            self.blackboard_lesson_layout.addItem(spacer)
                
                # 组之间添加分隔线（最后一组后不添加）
                if i < group_count - 1:
                    # 添加10px间隔
                    spacer_before = self.create_spacer(10)
                    if spacer_before:
                        self.blackboard_lesson_layout.addItem(spacer_before)
                    
                    # 添加分隔线
                    divider = self.create_blackboard_divider()
                    if divider:
                        self.blackboard_lesson_layout.addWidget(divider)
                    
                    # 添加10px间隔
                    spacer_after = self.create_spacer(10)
                    if spacer_after:
                        self.blackboard_lesson_layout.addItem(spacer_after)
            
            logger.info("熄屏模式课程显示更新完成")
            
        except Exception as e:
            logger.error(f"显示熄屏模式课程失败: {e}")

    def display_whiteboard_lessons(self):
        """显示白板模式课程"""
        try:
            if not self.whiteboard_lesson_layout:
                logger.error("白板模式课程布局未初始化")
                return
                
            # 获取当前课程
            current_lessons = self.app_contexts.get('Current_Lessons', {})
            if not current_lessons:
                logger.info("没有找到当前课程数据")
                return
                
            logger.info(f"获取到白板模式课程数据: {current_lessons}")
            
            # 清空课程框架字典和状态
            self.whiteboard_course_frames.clear()
            self.whiteboard_current_course_id = None
            self.whiteboard_previous_highlight_id = None
            self.whiteboard_current_state = None
            
            # 按时间段分组
            lesson_groups = self.group_lessons_by_period(current_lessons)
            logger.info(f"白板模式分组后的课程: {lesson_groups}")
            
            # 清空现有布局
            self.clear_whiteboard_lesson_layout()
            
            # 动态创建课程显示
            group_count = len(lesson_groups)
            for i, (period, lessons) in enumerate(lesson_groups.items()):
                # 获取这个时间段的所有课程ID
                period_course_ids = [key for key in current_lessons.keys() if key[1] == period]
                
                # 添加本组的课程
                for j, (course_id, abbreviation) in enumerate(zip(period_course_ids, lessons)):
                    frame = self.create_whiteboard_lesson_frame(abbreviation, course_id)
                    if frame:
                        self.whiteboard_lesson_layout.addWidget(frame)
                        # 存储课程框架引用
                        self.whiteboard_course_frames[course_id] = frame
                        logger.debug(f"添加白板模式课程框架: {abbreviation} (ID: {course_id})")
                    
                    # 课程之间添加6px间隔（最后一个课程后不添加）
                    if j < len(lessons) - 1:
                        spacer = self.create_spacer(6)
                        if spacer:
                            self.whiteboard_lesson_layout.addItem(spacer)
                
                # 组之间添加分隔线（最后一组后不添加）
                if i < group_count - 1:
                    # 添加10px间隔
                    spacer_before = self.create_spacer(10)
                    if spacer_before:
                        self.whiteboard_lesson_layout.addItem(spacer_before)
                    
                    # 添加分隔线
                    divider = self.create_whiteboard_divider()
                    if divider:
                        self.whiteboard_lesson_layout.addWidget(divider)
                    
                    # 添加10px间隔
                    spacer_after = self.create_spacer(10)
                    if spacer_after:
                        self.whiteboard_lesson_layout.addItem(spacer_after)
            
            logger.info("白板模式课程显示更新完成")
            
        except Exception as e:
            logger.error(f"显示白板模式课程失败: {e}")

    def create_blackboard_lesson_frame(self, abbreviation, course_id):
        """创建熄屏模式课程显示框架"""
        try:
            # 创建框架
            frame = QFrame()
            frame.setObjectName(f"blackboard_frame_{course_id}")
            frame.setMinimumSize(40, 40)
            frame.setMaximumSize(16777215, 40)
            frame.setStyleSheet("border-radius: 20px; background-color: none")
            frame.setFrameShape(QFrame.StyledPanel)
            frame.setFrameShadow(QFrame.Raised)
            
            # 创建布局
            layout = QHBoxLayout(frame)
            layout.setSpacing(0)
            layout.setContentsMargins(6, 0, 6, 0)
            
            # 创建标签 - 使用深色模式样式（白色文字）
            label = QLabel(abbreviation)
            label.setObjectName(f"blackboard_label_{course_id}")
            label.setFont(self.create_lesson_font())
            label.setStyleSheet("border: none; color: rgb(255, 255, 255); font-weight: bold; background: none;")
            label.setTextFormat(Qt.PlainText)
            label.setAlignment(Qt.AlignLeading | Qt.AlignLeft | Qt.AlignVCenter)
            
            layout.addWidget(label)
            
            return frame
            
        except Exception as e:
            logger.error(f"创建熄屏模式课程框架失败: {e}")
            return None

    def create_blackboard_divider(self):
        """创建熄屏模式分隔线"""
        try:
            divider = QLabel("|")
            divider.setFont(self.create_lesson_font())
            divider.setStyleSheet("border: none; color: rgb(255, 255, 255); font-weight: bold; background: none;")
            divider.setTextFormat(Qt.PlainText)
            divider.setAlignment(Qt.AlignCenter)
            return divider
        except Exception as e:
            logger.error(f"创建熄屏模式分隔线失败: {e}")
            return None

    def clear_blackboard_lesson_layout(self):
        """清空熄屏模式课程布局"""
        if not self.blackboard_lesson_layout:
            return
            
        # 清空课程框架字典
        self.blackboard_course_frames.clear()
        
        # 移除所有子项
        while self.blackboard_lesson_layout.count():
            item = self.blackboard_lesson_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.spacerItem():
                self.blackboard_lesson_layout.removeItem(item)

    
    def create_whiteboard_lesson_frame(self, abbreviation, course_id):
        """创建白板模式课程显示框架"""
        try:
            # 创建框架
            frame = QFrame()
            frame.setObjectName(f"whiteboard_frame_{course_id}")
            frame.setMinimumSize(40, 40)
            frame.setMaximumSize(16777215, 40)
            frame.setStyleSheet("border-radius: 20px; background-color: none")
            frame.setFrameShape(QFrame.StyledPanel)
            frame.setFrameShadow(QFrame.Raised)
            
            # 创建布局
            layout = QHBoxLayout(frame)
            layout.setSpacing(0)
            layout.setContentsMargins(6, 0, 6, 0)
            
            # 创建标签 - 使用浅色模式样式（黑色文字）
            label = QLabel(abbreviation)
            label.setObjectName(f"whiteboard_label_{course_id}")
            label.setFont(self.create_lesson_font())
            label.setStyleSheet("border: none; color: rgb(0, 0, 0); font-weight: bold; background: none;")
            label.setTextFormat(Qt.PlainText)
            label.setAlignment(Qt.AlignLeading | Qt.AlignLeft | Qt.AlignVCenter)
            
            layout.addWidget(label)
            
            return frame
            
        except Exception as e:
            logger.error(f"创建白板模式课程框架失败: {e}")
            return None

    def create_whiteboard_divider(self):
        """创建白板模式分隔线"""
        try:
            divider = QLabel("|")
            divider.setFont(self.create_lesson_font())
            divider.setStyleSheet("border: none; color: rgb(0, 0, 0); font-weight: bold; background: none;")
            divider.setTextFormat(Qt.PlainText)
            divider.setAlignment(Qt.AlignCenter)
            return divider
        except Exception as e:
            logger.error(f"创建白板模式分隔线失败: {e}")
            return None

    def clear_whiteboard_lesson_layout(self):
        """清空白板模式课程布局"""
        if not self.whiteboard_lesson_layout:
            return
            
        # 清空课程框架字典
        self.whiteboard_course_frames.clear()
        
        # 移除所有子项
        while self.whiteboard_lesson_layout.count():
            item = self.whiteboard_lesson_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.spacerItem():
                self.whiteboard_lesson_layout.removeItem(item)

    def setup_blackboard_button_styles(self):
        """设置熄屏模式按钮样式（深色模式样式）"""
        try:
            # 基础样式（深色模式）
            base_style = """
                QPushButton {
                    background-color: rgba(255, 255, 255, 50);
                    border: 1px solid;
                    border-color: rgba(255, 255, 255, 45);
                    border-top-color: rgba(255, 255, 255, 60);
                    border-radius: 17px;
                }
            """
            
            # 悬停样式
            hover_style = """
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 60);
                }
                QPushButton:pressed {
                    background-color: rgba(255, 255, 255, 40);
                    border-color: rgba(255, 255, 255, 25);
                    border-top-color: rgba(255, 255, 255, 30);
                }
            """
            
            # 应用样式到关闭按钮
            pushButton_close = self.blackboard_widget.findChild(QPushButton, "pushButton_close")
            if pushButton_close:
                pushButton_close.setStyleSheet(base_style + hover_style)
                
            # 应用样式到白板模式按钮
            pushButton_light = self.blackboard_widget.findChild(QPushButton, "pushButton_light")
            if pushButton_light:
                pushButton_light.setStyleSheet(base_style + hover_style)
                
            logger.debug("设置熄屏模式按钮样式完成")
            
        except Exception as e:
            logger.error(f"设置熄屏模式按钮样式失败: {e}")

    def setup_whiteboard_button_styles(self):
        """设置白板模式按钮样式（浅色模式样式）"""
        try:
            # 基础样式（浅色模式）
            base_style = """
                QPushButton {
                    background-color: rgb(255, 255, 255);
                    border: 1px solid;
                    border-color: rgba(0, 0, 0, 20);
                    border-bottom-color: rgba(0, 0, 0, 40);
                    border-radius: 17px;
                }
            """
            
            # 悬停样式
            hover_style = """
                QPushButton:hover {
                    background-color: rgba(250, 250, 250, 200);
                    border-color: rgba(0, 0, 0, 25);
                    border-bottom-color: rgba(0, 0, 0, 45);
                }
                QPushButton:pressed {
                    background-color: rgba(240, 240, 240, 200);
                    border-color: rgba(0, 0, 0, 25);
                    border-bottom-color: rgba(0, 0, 0, 45);
                }
            """
            
            # 应用样式到关闭按钮
            pushButton_close = self.whiteboard_widget.findChild(QPushButton, "pushButton_close")
            if pushButton_close:
                pushButton_close.setStyleSheet(base_style + hover_style)
                
            # 应用样式到熄屏模式按钮
            pushButton_dark = self.whiteboard_widget.findChild(QPushButton, "pushButton_dark")
            if pushButton_dark:
                pushButton_dark.setStyleSheet(base_style + hover_style)
                
            logger.debug("设置白板模式按钮样式完成")
            
        except Exception as e:
            logger.error(f"设置白板模式按钮样式失败: {e}")

    def show_blackboard(self):
        """显示熄屏模式（带淡入动画，覆盖任务栏全屏）"""
        try:
            from PyQt5.QtCore import QPropertyAnimation, QEasingCurve
            
            # 如果已经在熄屏模式，直接返回
            if self.is_blackboard_mode:
                return
                
            logger.info("开启熄屏模式")
            
            # 初始化熄屏模式UI
            if not self.init_blackboard_ui():
                logger.error("熄屏模式UI初始化失败")
                return
                
            # 获取屏幕信息，包括任务栏区域
            screen = QApplication.primaryScreen()
            screen_geometry = screen.geometry()  # 屏幕总几何信息（包括任务栏）
            available_geometry = screen.availableGeometry()  # 可用几何信息（不包括任务栏）
            
            logger.debug(f"屏幕总尺寸: {screen_geometry.width()}x{screen_geometry.height()}")
            logger.debug(f"可用区域: {available_geometry.width()}x{available_geometry.height()}")
            
            # 设置覆盖任务栏的全屏尺寸
            # 使用屏幕总几何信息而不是可用几何信息
            self.blackboard_widget.setGeometry(screen_geometry)

            # 初始化当前课程高亮
            self.update_blackboard_current_course_highlight()

            # 初始化倒计时显示
            self.update_blackboard_countdown()
            
            # 设置初始透明度为0（完全透明）
            self.blackboard_widget.setWindowOpacity(0.0)
            
            # 显示窗口
            self.blackboard_widget.show()
            
            # 确保窗口获得焦点并置顶
            self.blackboard_widget.raise_()
            self.blackboard_widget.activateWindow()
            
            # 创建淡入动画
            self.blackboard_animation = QPropertyAnimation(self.blackboard_widget, b"windowOpacity")
            self.blackboard_animation.setDuration(500)  # 500毫秒
            self.blackboard_animation.setStartValue(0.0)
            self.blackboard_animation.setEndValue(1.0)
            self.blackboard_animation.setEasingCurve(QEasingCurve.InOutQuad)
            
            # 开始动画
            self.blackboard_animation.start()
            
            # 更新状态
            self.is_blackboard_mode = True

            
            logger.info("熄屏模式显示完成，覆盖任务栏全屏")
            
        except Exception as e:
            logger.error(f"显示熄屏模式失败: {e}")

    def close_blackboard(self):
        """关闭熄屏模式（带淡出动画）"""
        try:
            from PyQt5.QtCore import QPropertyAnimation, QEasingCurve
        
            # 如果不在熄屏模式，直接返回
            if not self.is_blackboard_mode or not self.blackboard_widget:
                return
                
            logger.info("关闭熄屏模式")
            
            # 确保鼠标显示
            self.show_mouse()
            
            # 停止鼠标检测计时器
            self.stop_mouse_detection()
            
            # 创建淡出动画
            self.blackboard_animation = QPropertyAnimation(self.blackboard_widget, b"windowOpacity")
            self.blackboard_animation.setDuration(500)  # 500毫秒
            self.blackboard_animation.setStartValue(1.0)
            self.blackboard_animation.setEndValue(0.0)
            self.blackboard_animation.setEasingCurve(QEasingCurve.InOutQuad)
            
            # 动画结束后关闭窗口
            self.blackboard_animation.finished.connect(self._on_blackboard_animation_finished)
            
            # 开始动画
            self.blackboard_animation.start()
            
        except Exception as e:
            logger.error(f"关闭熄屏模式失败: {e}")

    def _on_blackboard_animation_finished(self):
        """熄屏模式动画结束回调"""
        try:
            # 停止进度条动画
            if self.blackboard_progress_animation:
                self.blackboard_progress_animation.stop()
                  
            # 停止鼠标检测
            self.stop_mouse_detection()

            # 关闭窗口
            if self.blackboard_widget:
                self.blackboard_widget.close()
                self.blackboard_widget.deleteLater()
                self.blackboard_widget = None
                self.blackboard_lesson_layout = None
                self.blackboard_course_frames.clear()
            
            # 更新状态
            self.is_blackboard_mode = False
            self.current_blackboard_progress = 0
            
            logger.info("熄屏模式已关闭")
            
        except Exception as e:
            logger.error(f"熄屏模式动画结束处理失败: {e}")

    def show_whiteboard(self):
        """显示白板模式（带淡入动画，覆盖任务栏全屏）"""
        try:
            from PyQt5.QtCore import QPropertyAnimation, QEasingCurve
            
            # 如果已经在白板模式，直接返回
            if self.is_whiteboard_mode:
                return
                
            logger.info("开启白板模式")
            
            # 初始化白板模式UI
            if not self.init_whiteboard_ui():
                logger.error("白板模式UI初始化失败")
                return
                
            # 获取屏幕信息，包括任务栏区域
            screen = QApplication.primaryScreen()
            screen_geometry = screen.geometry()  # 屏幕总几何信息（包括任务栏）
            available_geometry = screen.availableGeometry()  # 可用几何信息（不包括任务栏）
            
            logger.debug(f"屏幕总尺寸: {screen_geometry.width()}x{screen_geometry.height()}")
            logger.debug(f"可用区域: {available_geometry.width()}x{available_geometry.height()}")
            
            # 设置覆盖任务栏的全屏尺寸
            # 使用屏幕总几何信息而不是可用几何信息
            self.whiteboard_widget.setGeometry(screen_geometry)

            # 初始化当前课程高亮
            self.update_whiteboard_current_course_highlight()

            # 初始化倒计时显示
            self.update_whiteboard_countdown()
            
            # 设置初始透明度为0（完全透明）
            self.whiteboard_widget.setWindowOpacity(0.0)
            
            # 显示窗口
            self.whiteboard_widget.show()
            
            # 确保窗口获得焦点并置顶
            self.whiteboard_widget.raise_()
            self.whiteboard_widget.activateWindow()
            
            # 创建淡入动画
            self.whiteboard_animation = QPropertyAnimation(self.whiteboard_widget, b"windowOpacity")
            self.whiteboard_animation.setDuration(500)  # 500毫秒
            self.whiteboard_animation.setStartValue(0.0)
            self.whiteboard_animation.setEndValue(1.0)
            self.whiteboard_animation.setEasingCurve(QEasingCurve.InOutQuad)
            
            # 开始动画
            self.whiteboard_animation.start()
            
            # 更新状态
            self.is_whiteboard_mode = True
            
            logger.info("白板模式显示完成，覆盖任务栏全屏")
            
        except Exception as e:
            logger.error(f"显示白板模式失败: {e}")

    def close_whiteboard(self):
        """关闭白板模式（带淡出动画）"""
        try:
            from PyQt5.QtCore import QPropertyAnimation, QEasingCurve
        
            # 如果不在白板模式，直接返回
            if not self.is_whiteboard_mode or not self.whiteboard_widget:
                return
                
            logger.info("关闭白板模式")
            
            # 确保鼠标显示
            self.show_mouse()
            
            # 停止鼠标检测计时器
            self.stop_mouse_detection()
            
            # 创建淡出动画
            self.whiteboard_animation = QPropertyAnimation(self.whiteboard_widget, b"windowOpacity")
            self.whiteboard_animation.setDuration(500)  # 500毫秒
            self.whiteboard_animation.setStartValue(1.0)
            self.whiteboard_animation.setEndValue(0.0)
            self.whiteboard_animation.setEasingCurve(QEasingCurve.InOutQuad)
            
            # 动画结束后关闭窗口
            self.whiteboard_animation.finished.connect(self._on_whiteboard_animation_finished)
            
            # 开始动画
            self.whiteboard_animation.start()
            
        except Exception as e:
            logger.error(f"关闭白板模式失败: {e}")

    
    def _on_whiteboard_animation_finished(self):
        """白板模式动画结束回调"""
        try:
            # 停止进度条动画
            if self.whiteboard_progress_animation:
                self.whiteboard_progress_animation.stop()
                
            # 停止鼠标检测
            self.stop_mouse_detection()
                
            # 关闭窗口
            if self.whiteboard_widget:
                self.whiteboard_widget.close()
                self.whiteboard_widget.deleteLater()
                self.whiteboard_widget = None
                self.whiteboard_lesson_layout = None
                self.whiteboard_course_frames.clear()
            
            # 更新状态
            self.is_whiteboard_mode = False
            self.current_whiteboard_progress = 0
            
            logger.info("白板模式已关闭")
            
        except Exception as e:
            logger.error(f"白板模式动画结束处理失败: {e}")

    def update_blackboard_current_course_highlight(self):
        """更新熄屏模式当前课程高亮显示"""
        try:
            # 如果不在熄屏模式，直接返回
            if not self.is_blackboard_mode or not self.blackboard_course_frames:
                return
                
            # 计算当前课程
            current_course_id = self.calculate_current_course()
            current_state = self.app_contexts.get('State', 0)
            
            # 如果当前课程和状态都没有变化，直接返回
            if (current_course_id == self.blackboard_current_course_id and 
                current_state == self.blackboard_current_state):
                return
                
            # 移除之前的高亮
            if (self.blackboard_previous_highlight_id and 
                self.blackboard_previous_highlight_id in self.blackboard_course_frames):
                previous_frame = self.blackboard_course_frames[self.blackboard_previous_highlight_id]
                previous_frame.setStyleSheet("border-radius: 20px; background-color: none")
                
                # 恢复标签颜色
                label = previous_frame.findChild(QLabel)
                if label:
                    label.setStyleSheet("border: none; color: rgb(255, 255, 255); font-weight: bold; background: none;")
            
            # 设置新的高亮
            if current_course_id and current_course_id in self.blackboard_course_frames:
                current_frame = self.blackboard_course_frames[current_course_id]
                
                # 根据状态设置颜色
                if current_state == 0:  # 课间
                    bg_color = "#57c7a5"
                else:  # 上课
                    bg_color = "#e98f83"
                    
                current_frame.setStyleSheet(f"border-radius: 20px; background-color: {bg_color};")
                
                # 设置标签颜色为白色
                label = current_frame.findChild(QLabel)
                if label:
                    label.setStyleSheet("border: none; color: #ffffff; font-weight: bold; background: none;")
                
                # 更新状态
                self.blackboard_previous_highlight_id = current_course_id
                self.blackboard_current_course_id = current_course_id
                self.blackboard_current_state = current_state
                
                logger.debug(f"更新熄屏模式课程高亮: {current_course_id}, 状态: {current_state}, 颜色: {bg_color}")
            
        except Exception as e:
            logger.error(f"更新熄屏模式课程高亮失败: {e}")

    def update_whiteboard_current_course_highlight(self):
        """更新白板模式当前课程高亮显示"""
        try:
            # 如果不在白板模式，直接返回
            if not self.is_whiteboard_mode or not self.whiteboard_course_frames:
                return
                
            # 计算当前课程
            current_course_id = self.calculate_current_course()
            current_state = self.app_contexts.get('State', 0)
            
            # 如果当前课程和状态都没有变化，直接返回
            if (current_course_id == self.whiteboard_current_course_id and 
                current_state == self.whiteboard_current_state):
                return
                
            # 移除之前的高亮
            if (self.whiteboard_previous_highlight_id and 
                self.whiteboard_previous_highlight_id in self.whiteboard_course_frames):
                previous_frame = self.whiteboard_course_frames[self.whiteboard_previous_highlight_id]
                previous_frame.setStyleSheet("border-radius: 20px; background-color: none")
                
                # 恢复标签颜色
                label = previous_frame.findChild(QLabel)
                if label:
                    label.setStyleSheet("border: none; color: rgb(0, 0, 0); font-weight: bold; background: none;")
            
            # 设置新的高亮
            if current_course_id and current_course_id in self.whiteboard_course_frames:
                current_frame = self.whiteboard_course_frames[current_course_id]
                
                # 根据状态设置颜色
                if current_state == 0:  # 课间
                    bg_color = "#57c7a5"
                else:  # 上课
                    bg_color = "#e98f83"
                    
                current_frame.setStyleSheet(f"border-radius: 20px; background-color: {bg_color};")
                
                # 设置标签颜色为白色
                label = current_frame.findChild(QLabel)
                if label:
                    label.setStyleSheet("border: none; color: #ffffff; font-weight: bold; background: none;")
                
                # 更新状态
                self.whiteboard_previous_highlight_id = current_course_id
                self.whiteboard_current_course_id = current_course_id
                self.whiteboard_current_state = current_state
                
                logger.debug(f"更新白板模式课程高亮: {current_course_id}, 状态: {current_state}, 颜色: {bg_color}")
            
        except Exception as e:
            logger.error(f"更新白板模式课程高亮失败: {e}")

    def update_blackboard_countdown(self):
        """更新熄屏模式倒计时显示（带动画）"""
        try:
            if not self.is_blackboard_mode or not self.blackboard_widget:
                return
                
            # 获取倒计时标签和进度条
            countdown_label = self.blackboard_widget.findChild(QLabel, "countdown")
            countdown_progress = self.blackboard_widget.findChild(QObject, "countdown_progressBar")
            
            if not countdown_label or not countdown_progress:
                logger.warning("未找到熄屏模式倒计时控件")
                return
            
            # 获取当前活动时间信息
            time_info = self.get_current_activity_time_info()
            
            # 修改判断逻辑：只有当整个time_info为None时才显示默认值
            if time_info is None:
                # 没有活动数据，显示默认值
                countdown_label.setText("< - 分钟")
                if hasattr(countdown_progress, 'setVal'):
                    # 使用动画设置进度条为0
                    self.animate_blackboard_progress(0)
                # 移除高亮显示
                self.clear_blackboard_highlight()
                logger.debug("没有活动数据，显示默认倒计时")
                return
                
            total_seconds, remaining_seconds, activity_id, state = time_info
            
            # 检查remaining_seconds是否为None，如果是则显示默认值
            if remaining_seconds is None:
                countdown_label.setText("< - 分钟")
                if hasattr(countdown_progress, 'setVal'):
                    self.animate_blackboard_progress(0)
                # 移除高亮显示
                self.clear_blackboard_highlight()
                logger.debug("剩余时间为None，显示默认倒计时")
                return
            
            # 更新倒计时文本
            if remaining_seconds >= 60:
                # 大于等于1分钟，显示分钟（向上取整）
                minutes = (remaining_seconds + 59) // 60  # 向上取整
                countdown_label.setText(f"< {minutes} 分钟")
            else:
                # 小于1分钟，显示秒（向上取整）
                seconds = max(1, remaining_seconds)  # 至少显示1秒
                countdown_label.setText(f"< {seconds} 秒")
            
            # 更新进度条（使用动画）
            if total_seconds is None:
                # 总时长为None，表示活动尚未开始，进度条显示100%
                progress_percentage = 100
                self.animate_blackboard_progress(progress_percentage)
                logger.debug("活动尚未开始，进度条设为100%")
            elif total_seconds > 0:
                progress_percentage = int(((total_seconds - remaining_seconds) / total_seconds) * 100)
                progress_percentage = max(0, min(100, progress_percentage))  # 限制在0-100之间
                
                self.animate_blackboard_progress(progress_percentage)
                logger.debug(f"活动进行中，进度条设为{progress_percentage}%")
            
            # 根据状态设置进度条颜色
            if state == 0:  # 课间
                progress_color = "#57c7a5"
            else:  # 上课
                progress_color = "#e98f83"
                
            # 设置进度条颜色（需要根据ProgressRing的实际API调整）
            progress_style = f"""
                ProgressRing {{
                    background-color: transparent;
                }}
                ProgressRing::chunk {{
                    background-color: {progress_color};
                }}
            """
            countdown_progress.setStyleSheet(progress_style)
            
            logger.debug(f"更新熄屏模式倒计时完成: 进度{progress_percentage if 'progress_percentage' in locals() else 'N/A'}%, 颜色: {progress_color}")
            
        except Exception as e:
            logger.error(f"更新熄屏模式倒计时失败: {e}")
            # 出错时也显示默认值
            try:
                countdown_label = self.blackboard_widget.findChild(QLabel, "countdown")
                countdown_progress = self.blackboard_widget.findChild(QObject, "countdown_progressBar")
                if countdown_label:
                    countdown_label.setText("< - 分钟")
                if countdown_progress and hasattr(countdown_progress, 'setVal'):
                    self.animate_blackboard_progress(0)
                # 移除高亮显示
                self.clear_blackboard_highlight()
            except:
                pass

    def clear_blackboard_highlight(self):
        """清除熄屏模式的高亮显示"""
        try:
            if not self.is_blackboard_mode or not self.blackboard_course_frames:
                return
                
            # 移除所有高亮
            for course_id, frame in self.blackboard_course_frames.items():
                frame.setStyleSheet("border-radius: 20px; background-color: none")
                label = frame.findChild(QLabel)
                if label:
                    label.setStyleSheet("border: none; color: rgb(255, 255, 255); font-weight: bold; background: none;")
            
            # 重置状态
            self.blackboard_previous_highlight_id = None
            self.blackboard_current_course_id = None
            self.blackboard_current_state = None
            
            logger.debug("已清除熄屏模式高亮显示")
            
        except Exception as e:
            logger.error(f"清除熄屏模式高亮失败: {e}")

    def clear_whiteboard_highlight(self):
        """清除白板模式的高亮显示"""
        try:
            if not self.is_whiteboard_mode or not self.whiteboard_course_frames:
                return
                
            # 移除所有高亮
            for course_id, frame in self.whiteboard_course_frames.items():
                frame.setStyleSheet("border-radius: 20px; background-color: none")
                label = frame.findChild(QLabel)
                if label:
                    label.setStyleSheet("border: none; color: rgb(0, 0, 0); font-weight: bold; background: none;")
            
            # 重置状态
            self.whiteboard_previous_highlight_id = None
            self.whiteboard_current_course_id = None
            self.whiteboard_current_state = None
            
            logger.debug("已清除白板模式高亮显示")
            
        except Exception as e:
            logger.error(f"清除白板模式高亮失败: {e}")

    def update_whiteboard_countdown(self):
        """更新白板模式倒计时显示（带动画）"""
        try:
            if not self.is_whiteboard_mode or not self.whiteboard_widget:
                return
                
            # 获取倒计时标签和进度条
            countdown_label = self.whiteboard_widget.findChild(QLabel, "countdown")
            countdown_progress = self.whiteboard_widget.findChild(QObject, "countdown_progressBar")
            
            if not countdown_label or not countdown_progress:
                logger.warning("未找到白板模式倒计时控件")
                return
            
            # 获取当前活动时间信息
            time_info = self.get_current_activity_time_info()

            # 修改判断逻辑：只有当整个time_info为None时才显示默认值
            if time_info is None:
                # 没有活动数据，显示默认值
                countdown_label.setText("< - 分钟")
                if hasattr(countdown_progress, 'setVal'):
                    # 使用动画设置进度条为0
                    self.animate_whiteboard_progress(0)
                # 移除高亮显示
                self.clear_whiteboard_highlight()
                logger.debug("没有活动数据，显示默认倒计时")
                return
                
            total_seconds, remaining_seconds, activity_id, state = time_info
            
            # 检查remaining_seconds是否为None，如果是则显示默认值
            if remaining_seconds is None:
                countdown_label.setText("< - 分钟")
                if hasattr(countdown_progress, 'setVal'):
                    self.animate_whiteboard_progress(0)
                # 移除高亮显示
                self.clear_whiteboard_highlight()
                logger.debug("剩余时间为None，显示默认倒计时")
                return
            
            # 更新倒计时文本
            if remaining_seconds >= 60:
                # 大于等于1分钟，显示分钟（向上取整）
                minutes = (remaining_seconds + 59) // 60  # 向上取整
                countdown_label.setText(f"< {minutes} 分钟")
            else:
                # 小于1分钟，显示秒（向上取整）
                seconds = max(1, remaining_seconds)  # 至少显示1秒
                countdown_label.setText(f"< {seconds} 秒")
            
            # 更新进度条（使用动画）
            if total_seconds is None:
                # 总时长为None，表示活动尚未开始，进度条显示100%
                progress_percentage = 100
                self.animate_whiteboard_progress(progress_percentage)
                logger.debug("活动尚未开始，进度条设为100%")
            elif total_seconds > 0:
                progress_percentage = int(((total_seconds - remaining_seconds) / total_seconds) * 100)
                progress_percentage = max(0, min(100, progress_percentage))  # 限制在0-100之间
                
                self.animate_whiteboard_progress(progress_percentage)
                logger.debug(f"活动进行中，进度条设为{progress_percentage}%")
            
            # 根据状态设置进度条颜色（和熄屏模式一样）
            if state == 0:  # 课间
                progress_color = "#57c7a5"
            else:  # 上课
                progress_color = "#e98f83"
                
            # 设置进度条颜色（需要根据ProgressRing的实际API调整）
            progress_style = f"""
                ProgressRing {{
                    background-color: transparent;
                }}
                ProgressRing::chunk {{
                    background-color: {progress_color};
                }}
            """
            countdown_progress.setStyleSheet(progress_style)
            
            logger.debug(f"更新白板模式倒计时: 进度{progress_percentage}%, 颜色: {progress_color}")
            
        except Exception as e:
            logger.error(f"更新白板模式倒计时失败: {e}")
            # 出错时也显示默认值
            try:
                countdown_label = self.whiteboard_widget.findChild(QLabel, "countdown")
                countdown_progress = self.whiteboard_widget.findChild(QObject, "countdown_progressBar")
                if countdown_label:
                    countdown_label.setText("< - 分钟")
                if countdown_progress and hasattr(countdown_progress, 'setVal'):
                    self.animate_whiteboard_progress(0)
                # 移除高亮显示
                self.clear_whiteboard_highlight()
            except:
                pass

    def switch_to_blackboard_from_whiteboard(self):
        """从白板模式切换到熄屏模式"""
        try:
            logger.info("从白板模式切换到熄屏模式")
            # 先关闭白板模式
            self.close_whiteboard()
            # 然后打开熄屏模式
            self.show_blackboard()
        except Exception as e:
            logger.error(f"从白板模式切换到熄屏模式失败: {e}")

    def switch_to_whiteboard_from_blackboard(self):
        """从熄屏模式切换到白板模式"""
        try:
            logger.info("从熄屏模式切换到白板模式")
            # 先关闭熄屏模式
            self.close_blackboard()
            # 然后打开白板模式
            self.show_whiteboard()
        except Exception as e:
            logger.error(f"从熄屏模式切换到白板模式失败: {e}")

    def init_blackboard_progress_animation(self):
        """初始化熄屏模式进度条动画"""
        try:
            from PyQt5.QtCore import QPropertyAnimation, QEasingCurve
            
            countdown_progress = self.blackboard_widget.findChild(QObject, "countdown_progressBar")
            if countdown_progress:
                self.blackboard_progress_animation = QPropertyAnimation(countdown_progress, b"val")
                self.blackboard_progress_animation.setDuration(800)  # 800毫秒动画时长
                self.blackboard_progress_animation.setEasingCurve(QEasingCurve.OutCubic)
                self.current_blackboard_progress = 0
                logger.debug("初始化熄屏模式进度条动画完成")
        except Exception as e:
            logger.error(f"初始化熄屏模式进度条动画失败: {e}")

    def init_whiteboard_progress_animation(self):
        """初始化白板模式进度条动画"""
        try:
            from PyQt5.QtCore import QPropertyAnimation, QEasingCurve
            
            countdown_progress = self.whiteboard_widget.findChild(QObject, "countdown_progressBar")
            if countdown_progress:
                self.whiteboard_progress_animation = QPropertyAnimation(countdown_progress, b"val")
                self.whiteboard_progress_animation.setDuration(800)  # 800毫秒动画时长
                self.whiteboard_progress_animation.setEasingCurve(QEasingCurve.OutCubic)
                self.current_whiteboard_progress = 0
                logger.debug("初始化白板模式进度条动画完成")
        except Exception as e:
            logger.error(f"初始化白板模式进度条动画失败: {e}")

    def animate_blackboard_progress(self, target_progress):
        """动画更新熄屏模式进度条"""
        try:
            if (not self.blackboard_progress_animation or 
                not self.is_blackboard_mode or 
                not self.blackboard_widget):
                return
                
            countdown_progress = self.blackboard_widget.findChild(QObject, "countdown_progressBar")
            if not countdown_progress:
                return
                
            # 停止当前动画
            self.blackboard_progress_animation.stop()
            
            # 设置动画范围
            self.blackboard_progress_animation.setStartValue(self.current_blackboard_progress)
            self.blackboard_progress_animation.setEndValue(target_progress)
            
            # 开始动画
            self.blackboard_progress_animation.start()
            
            # 更新当前进度
            self.current_blackboard_progress = target_progress
            
        except Exception as e:
            logger.error(f"熄屏模式进度条动画失败: {e}")

    def animate_whiteboard_progress(self, target_progress):
        """动画更新白板模式进度条"""
        try:
            if (not self.whiteboard_progress_animation or 
                not self.is_whiteboard_mode or 
                not self.whiteboard_widget):
                return
                
            countdown_progress = self.whiteboard_widget.findChild(QObject, "countdown_progressBar")
            if not countdown_progress:
                return
                
            # 停止当前动画
            self.whiteboard_progress_animation.stop()
            
            # 设置动画范围
            self.whiteboard_progress_animation.setStartValue(self.current_whiteboard_progress)
            self.whiteboard_progress_animation.setEndValue(target_progress)
            
            # 开始动画
            self.whiteboard_progress_animation.start()
            
            # 更新当前进度
            self.current_whiteboard_progress = target_progress
            
        except Exception as e:
            logger.error(f"白板模式进度条动画失败: {e}")

    def init_mouse_detection(self):
        """初始化鼠标检测"""
        try:
            # 重置鼠标状态
            self.mouse_hidden = False
            self.mouse_stationary_time = 0
            self.last_mouse_position = None
            
            # 创建鼠标检测计时器
            if not self.mouse_hide_timer:
                self.mouse_hide_timer = QTimer()
                self.mouse_hide_timer.timeout.connect(self.check_mouse_movement)
            
            # 启动鼠标检测
            self.mouse_hide_timer.start(self.mouse_check_interval)
            logger.info("鼠标检测已启动")
            
        except Exception as e:
            logger.error(f"初始化鼠标检测失败: {e}")

    def check_mouse_movement(self):
        """检查鼠标移动状态"""
        try:
            # 只有在熄屏模式或白板模式下才检测鼠标
            if not self.is_blackboard_mode and not self.is_whiteboard_mode:
                return
                
            # 获取当前鼠标位置
            current_pos = self.get_mouse_position()
            
            if current_pos:
                # 如果是第一次获取位置，直接记录
                if self.last_mouse_position is None:
                    self.last_mouse_position = current_pos
                    return
                    
                # 检查鼠标是否移动
                if current_pos != self.last_mouse_position:
                    # 鼠标移动了，重置静止时间并显示鼠标
                    self.mouse_stationary_time = 0
                    self.last_mouse_position = current_pos
                    
                    if self.mouse_hidden:
                        self.show_mouse()
                else:
                    # 鼠标静止，增加静止时间
                    self.mouse_stationary_time += self.mouse_check_interval / 1000.0
                    
                    # 如果静止时间超过阈值且鼠标未隐藏，则隐藏鼠标
                    if self.mouse_stationary_time >= (self.mouse_hide_delay / 1000.0) and not self.mouse_hidden:
                        self.hide_mouse()
                        
        except Exception as e:
            logger.error(f"检查鼠标移动失败: {e}")

    def hide_mouse(self):
        """隐藏鼠标光标"""
        try:
            if not self.mouse_hidden:
                # 只在熄屏模式或白板模式下隐藏鼠标
                if self.is_blackboard_mode and self.blackboard_widget:
                    self.blackboard_widget.setCursor(Qt.BlankCursor)
                    self.mouse_hidden = True
                    logger.debug("鼠标已隐藏（熄屏模式）")
                elif self.is_whiteboard_mode and self.whiteboard_widget:
                    self.whiteboard_widget.setCursor(Qt.BlankCursor)
                    self.mouse_hidden = True
                    logger.debug("鼠标已隐藏（白板模式）")
                    
        except Exception as e:
            logger.error(f"隐藏鼠标失败: {e}")

    def show_mouse(self):
        """显示鼠标光标"""
        try:
            if self.mouse_hidden:
                # 恢复默认鼠标光标
                if self.is_blackboard_mode and self.blackboard_widget:
                    self.blackboard_widget.unsetCursor()
                    self.mouse_hidden = False
                    logger.debug("鼠标已显示（熄屏模式）")
                elif self.is_whiteboard_mode and self.whiteboard_widget:
                    self.whiteboard_widget.unsetCursor()
                    self.mouse_hidden = False
                    logger.debug("鼠标已显示（白板模式）")
                    
        except Exception as e:
            logger.error(f"显示鼠标失败: {e}")

    def stop_mouse_detection(self):
        """停止鼠标检测"""
        try:
            if self.mouse_hide_timer and self.mouse_hide_timer.isActive():
                self.mouse_hide_timer.stop()
                logger.info("鼠标检测已停止")
                
            # 重置鼠标状态
            self.mouse_hidden = False
            self.mouse_stationary_time = 0
            self.last_mouse_position = None
            
        except Exception as e:
            logger.error(f"停止鼠标检测失败: {e}")

    def get_mouse_position(self):
        """获取鼠标位置"""
        try:
            point = wintypes.POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
                return (point.x, point.y)
            return None
        except Exception as e:
            logger.error(f"获取鼠标位置失败: {e}")
            return None