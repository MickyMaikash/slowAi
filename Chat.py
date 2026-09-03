import sys
import json
import requests
import markdown
import os
import re

from Database import ChatDB

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QPlainTextEdit,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QComboBox,
    QSizePolicy,
    QMessageBox,
)

from PySide6.QtCore import (
    Qt,
    QObject,
    Signal,
    Slot,
    QThread,
    QTimer,
    QRectF,
    QPropertyAnimation,
    QEasingCurve,
    Property,
)

from PySide6.QtGui import (
    QIcon,
    QFont,
    QPainter,
    QPen,
    QFontMetrics,
)


# =========================================================
# CIRCULAR LOADING INDICATOR
# =========================================================

class CircularLoader(QWidget):

    def __init__(self, parent=None):

        super().__init__(parent)

        self.angle = 0

        self.setFixedSize(
            18,
            18
        )

        self.setAttribute(
            Qt.WA_TransparentForMouseEvents,
            True
        )

        self.timer = QTimer(
            self
        )

        self.timer.setInterval(
            45
        )

        self.timer.timeout.connect(
            self.rotate
        )

        self.hide()

    def start(self):

        self.show()

        if not self.timer.isActive():

            self.timer.start()

        self.raise_()

    def stop(self):

        self.timer.stop()

        self.hide()

    def rotate(self):

        self.angle = (
            self.angle + 15
        ) % 360

        self.update()

    def paintEvent(
        self,
        event
    ):

        painter = QPainter(
            self
        )

        painter.setRenderHint(
            QPainter.Antialiasing
        )

        backgroundPen = QPen(
            Qt.GlobalColor.darkGray
        )

        backgroundPen.setWidth(
            2
        )

        painter.setPen(
            backgroundPen
        )

        rect = QRectF(
            2,
            2,
            14,
            14
        )

        painter.drawArc(
            rect,
            0,
            360 * 16
        )

        activePen = QPen(
            Qt.GlobalColor.white
        )

        activePen.setWidth(
            2
        )

        activePen.setCapStyle(
            Qt.RoundCap
        )

        painter.setPen(
            activePen
        )

        painter.drawArc(
            rect,
            self.angle * 16,
            110 * 16
        )

        painter.end()


# =========================================================
# OLLAMA WORKER
# =========================================================

class OllamaWorker(QObject):

    chunkReceived = Signal(
        int,
        str
    )

    finished = Signal(
        int,
        str
    )

    error = Signal(
        int,
        str
    )

    modelsReceived = Signal(
        list
    )

    modelsError = Signal(
        str
    )

    def __init__(
        self,
        chat_id=None,
        messages=None,
        model="llama3.2"
    ):

        super().__init__()

        self.chat_id = chat_id
        self.messages = messages or []
        self.model = model

    @Slot()
    def run(self):

        response = None

        try:

            response = requests.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": self.model,
                    "messages": self.messages,
                    "stream": True
                },
                stream=True,
                timeout=(10, 300)
            )

            response.raise_for_status()

            full_response = ""

            for line in response.iter_lines():

                if not line:

                    continue

                try:

                    data = json.loads(
                        line.decode("utf-8")
                    )

                except json.JSONDecodeError:

                    continue

                message = data.get(
                    "message"
                )

                if message:

                    content = message.get(
                        "content",
                        ""
                    )

                    if content:

                        full_response += content

                        self.chunkReceived.emit(
                            self.chat_id,
                            content
                        )

                if data.get("done"):

                    break

            self.finished.emit(
                self.chat_id,
                full_response
            )

        except requests.exceptions.ConnectionError:

            self.error.emit(
                self.chat_id,
                "Could not connect to Ollama.\n\n"
                "Make sure Ollama is running."
            )

        except requests.exceptions.Timeout:

            self.error.emit(
                self.chat_id,
                "Ollama took too long to respond."
            )

        except requests.exceptions.RequestException as e:

            self.error.emit(
                self.chat_id,
                f"Ollama request failed:\n{e}"
            )

        except Exception as e:

            self.error.emit(
                self.chat_id,
                str(e)
            )

        finally:

            if response is not None:

                try:

                    response.close()

                except Exception:

                    pass

    @Slot()
    def loadModels(self):

        response = None

        try:

            response = requests.get(
                "http://localhost:11434/api/tags",
                timeout=10
            )

            response.raise_for_status()

            data = response.json()

            models = [
                model["name"]
                for model in data.get(
                    "models",
                    []
                )
                if "name" in model
            ]

            self.modelsReceived.emit(
                models
            )

        except requests.exceptions.ConnectionError:

            self.modelsError.emit(
                "Could not connect to Ollama."
            )

        except requests.exceptions.Timeout:

            self.modelsError.emit(
                "Could not load models from Ollama."
            )

        except requests.exceptions.RequestException as e:

            self.modelsError.emit(
                f"Could not load Ollama models:\n{e}"
            )

        except Exception as e:

            self.modelsError.emit(
                str(e)
            )

        finally:

            if response is not None:

                try:

                    response.close()

                except Exception:

                    pass


# =========================================================
# CHAT BUTTON
# =========================================================

class ChatButton(QPushButton):

    longPressed = Signal()

    def __init__(
        self,
        chat_id,
        name
    ):

        super().__init__()

        self.chat_id = chat_id
        self.chatName = name

        self.setToolTip(
            name
        )

        self.longPressTimer = QTimer(
            self
        )

        self.longPressTimer.setSingleShot(
            True
        )

        self.longPressTimer.setInterval(
            700
        )

        self.longPressTimer.timeout.connect(
            self.handleLongPress
        )

        self.longPressedState = False

        self.loader = CircularLoader(
            self
        )

        self.nameLabel = QLabel(
            self
        )

        self.nameLabel.setAlignment(
            Qt.AlignLeft |
            Qt.AlignVCenter
        )

        self.nameLabel.setAttribute(
            Qt.WA_TransparentForMouseEvents,
            True
        )

        self.nameLabel.setStyleSheet("""
            QLabel {
                background: transparent;
                color: #cfcfcf;
                font-size: 14px;
            }
        """)

        self.setFixedHeight(
            44
        )

        self.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed
        )

        self.setCursor(
            Qt.PointingHandCursor
        )

        self.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #cfcfcf;
                border: none;
                border-radius: 10px;
                margin: 0px;
                padding: 0px;
            }

            QPushButton:hover {
                background-color: #2b2b2b;
            }

            QPushButton:pressed {
                background-color: #333333;
            }
        """)

        self.updateChatName()

    def updateChatName(self):

        availableWidth = max(
            0,
            self.width() - 52
        )

        fontMetrics = QFontMetrics(
            self.nameLabel.font()
        )

        text = fontMetrics.elidedText(
            self.chatName,
            Qt.ElideRight,
            availableWidth
        )

        self.nameLabel.setText(
            text
        )

    def resizeEvent(
        self,
        event
    ):

        super().resizeEvent(
            event
        )

        availableWidth = max(
            0,
            self.width() - 52
        )

        self.nameLabel.setGeometry(
            12,
            0,
            availableWidth,
            self.height()
        )

        self.updateChatName()

        self.loader.move(
            self.width() - self.loader.width() - 10,
            (self.height() - self.loader.height()) // 2
        )

        self.loader.raise_()

    def startLoading(self):

        self.loader.start()

        self.loader.raise_()

    def stopLoading(self):

        self.loader.stop()

    def setSelected(
        self,
        selected
    ):

        if selected:

            self.setStyleSheet("""
                QPushButton {
                    background-color: #343434;
                    color: #ffffff;
                    border: 1px solid #444444;
                    border-radius: 10px;
                    margin: 0px;
                    padding: 0px;
                }

                QPushButton:hover {
                    background-color: #3a3a3a;
                }
            """)

            self.nameLabel.setStyleSheet("""
                QLabel {
                    background: transparent;
                    color: #ffffff;
                    font-size: 14px;
                }
            """)

        else:

            self.setStyleSheet("""
                QPushButton {
                    background-color: transparent;
                    color: #cfcfcf;
                    border: none;
                    border-radius: 10px;
                    margin: 0px;
                    padding: 0px;
                }

                QPushButton:hover {
                    background-color: #2b2b2b;
                }

                QPushButton:pressed {
                    background-color: #333333;
                }
            """)

            self.nameLabel.setStyleSheet("""
                QLabel {
                    background: transparent;
                    color: #cfcfcf;
                    font-size: 14px;
                }
            """)

        self.loader.raise_()

    def handleLongPress(self):

        self.longPressedState = True

        self.longPressed.emit()

    def mousePressEvent(
        self,
        event
    ):

        if event.button() == Qt.LeftButton:

            self.longPressedState = False

            self.longPressTimer.start()

        super().mousePressEvent(
            event
        )

    def mouseReleaseEvent(
        self,
        event
    ):

        if self.longPressTimer.isActive():

            self.longPressTimer.stop()

        if self.longPressedState:

            self.longPressedState = False

            event.accept()

            return

        super().mouseReleaseEvent(
            event
        )


# =========================================================
# COPY BUTTON
# =========================================================

class CopyButton(QPushButton):

    def __init__(self):

        super().__init__(
            "Copy"
        )

        self.setFixedHeight(
            26
        )

        self.setCursor(
            Qt.PointingHandCursor
        )

        self.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #999999;
                border: none;
                border-radius: 6px;
                padding: 3px 8px;
                font-size: 12px;
            }

            QPushButton:hover {
                background-color: #3d3d3d;
                color: white;
            }
        """)


# =========================================================
# CODE BLOCK
# =========================================================

class CodeBlock(QFrame):

    def __init__(
        self,
        code,
        language=""
    ):

        super().__init__()

        self.code = code

        self.setStyleSheet("""
            QFrame {
                background-color: #1e1e1e;
                border-radius: 7px;
                border: 1px solid #333333;
            }
        """)

        layout = QVBoxLayout(
            self
        )

        layout.setContentsMargins(
            0,
            0,
            0,
            0
        )

        layout.setSpacing(
            0
        )

        header = QWidget()
        header.setFixedHeight(32)
        headerLayout = QHBoxLayout(
            header
        )

        headerLayout.setContentsMargins(
            10,
            4,
            5,
            4
        )

        languageLabel = QLabel(
            f"</> {language}" if language else "code"
        )

        languageLabel.setStyleSheet("""
            QLabel {
                color: #888888;
                background: transparent;
                font-size: 12px;
            }
        """)

        headerLayout.addWidget(
            languageLabel
        )

        headerLayout.addStretch()

        self.copyButton = CopyButton()
        self.copyButton.setFixedHeight(24)
        self.copyButton.clicked.connect(
            self.copyCode
        )

        headerLayout.addWidget(
            self.copyButton
        )

        layout.addWidget(
            header
        )

        self.codeEdit = QPlainTextEdit()

        self.codeEdit.setPlainText(
            self.code
        )

        self.codeEdit.setReadOnly(
            True
        )

        self.codeEdit.setLineWrapMode(
            QPlainTextEdit.NoWrap
        )

        self.codeEdit.setFont(
            QFont(
                "Consolas",
                18
            )
        )

        self.codeEdit.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #dcdcdc;
                border: none;
                padding: 4px 10px;
                font-family: Consolas;
                font-size: 18px;
            }

            QScrollBar:vertical {
                background: #1e1e1e;
                width: 8px;
            }

            QScrollBar::handle:vertical {
                background: #444444;
                border-radius: 4px;
            }

            QScrollBar:horizontal {
                background: #1e1e1e;
                height: 8px;
            }

            QScrollBar::handle:horizontal {
                background: #444444;
                border-radius: 4px;
            }
        """)

        lineCount = (
            self.code.count("\n") + 1
        )

        height = max(
            55,
            min(
                lineCount * 32 + 16,
                600
            )
        )

        self.codeEdit.setFixedHeight(
            height
        )

        layout.addWidget(
            self.codeEdit
        )

    def copyCode(self):

        QApplication.clipboard().setText(
            self.code
        )

        self.copyButton.setText(
            "Copied!"
        )

        QTimer.singleShot(
            1200,
            lambda:
            self.copyButton.setText(
                "Copy"
            )
        )


# =========================================================
# AI CONTENT
# =========================================================

class AIContent(QWidget):

    def __init__(
        self,
        text
    ):

        super().__init__()

        self.text = text

        layout = QVBoxLayout(
            self
        )

        layout.setContentsMargins(
            0,
            0,
            0,
            0
        )

        layout.setSpacing(
            10
        )

        self.buildContent(
            layout
        )

    def buildContent(
        self,
        layout
    ):

        pattern = re.compile(
            r"```([^\n`]*)\n(.*?)```",
            re.DOTALL
        )

        lastIndex = 0

        for match in pattern.finditer(
            self.text
        ):

            normalText = self.text[
                lastIndex:match.start()
            ]

            if normalText.strip():

                self.addMarkdown(
                    layout,
                    normalText
                )

            language = match.group(
                1
            ).strip()

            code = match.group(
                2
            )

            codeBlock = CodeBlock(
                code,
                language
            )

            layout.addWidget(
                codeBlock
            )

            lastIndex = match.end()

        remainingText = self.text[
            lastIndex:
        ]

        if remainingText.strip():

            self.addMarkdown(
                layout,
                remainingText
            )

    def addMarkdown(
        self,
        layout,
        text
    ):

        html = markdown.markdown(
            text,
            extensions=[
                "extra",
                "tables",
                "nl2br"
            ]
        )

        html = f"""
        <style>

            body {{
                color: #eeeeee;
                font-size: 18px;
                font-family: Arial;
            }}

            p {{
                margin-top: 4px;
                margin-bottom: 8px;
                font-size: 18px;
            }}

            h1 {{
                font-size: 27px;
                margin-top: 8px;
                margin-bottom: 8px;
            }}

            h2 {{
                font-size: 24px;
                margin-top: 8px;
                margin-bottom: 8px;
            }}

            h3 {{
                font-size: 21px;
                margin-top: 8px;
                margin-bottom: 8px;
            }}

            strong {{
                font-size: 18px;
            }}

            li {{
                font-size: 18px;
                margin-bottom: 4px;
            }}

            ul {{
                margin-left: 18px;
            }}

            ol {{
                margin-left: 18px;
            }}

            a {{
                color: #6ea8fe;
                font-size: 18px;
            }}

            blockquote {{
                color: #aaaaaa;
                border-left: 3px solid #555555;
                padding-left: 10px;
                font-size: 18px;
            }}

            code {{
                background-color: #383838;
                color: #eeeeee;
                padding: 2px 5px;
                border-radius: 4px;
                font-family: Consolas;
                font-size: 17px;
            }}

            table {{
                border-collapse: collapse;
            }}

            th {{
                background-color: #383838;
                padding: 7px;
                border: 1px solid #555555;
            }}

            td {{
                padding: 7px;
                border: 1px solid #555555;
            }}

        </style>

        {html}
        """

        label = QLabel()

        label.setTextFormat(
            Qt.RichText
        )

        label.setText(
            html
        )

        label.setWordWrap(
            True
        )

        label.setTextInteractionFlags(
            Qt.TextSelectableByMouse |
            Qt.LinksAccessibleByMouse
        )

        label.setOpenExternalLinks(
            True
        )

        label.setStyleSheet("""
            QLabel {
                background: transparent;
                color: #eeeeee;
                font-size: 18px;
            }
        """)

        label.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Minimum
        )

        layout.addWidget(
            label
        )


# =========================================================
# MAIN WINDOW
# =========================================================

class MainWindow(QMainWindow):

    def __init__(self):

        super().__init__()

        self.ChatDb = ChatDB()

        self.currentChatId = None
        self.currentChatName = None

        self.setWindowTitle(
            "slowAi"
        )

        self.setFixedSize(
            900,
            635
        )

        self.messages = []

        self.activeRequests = {}

        self.sidebarExpanded = True
        self.sidebarWidth = 225

        self.chatButtons = {}

        self.sidebarAnimation = None

        # =================================================
        # SIDEBAR SCROLL ANCHOR
        # =================================================

        self.scrollAnchorWidget = None
        self.scrollAnchorOffset = 0
        self.sidebarWasAtBottom = False

        self.modelsWorker = None
        self.modelsThread = None

        self.loadingWidget = None
        self.loadingTimer = None
        self.loadingLabel = None
        self.loadingDots = 0

        self.aiBubble = None
        self.aiStreamingLabel = None

        self.currentQuestionRow = None

        self.userScrolledUp = False

        self.programmaticScroll = False

        # =================================================
        # AUTO SCROLL TIMER
        # =================================================

        self.autoScrollTimer = QTimer(
            self
        )

        self.autoScrollTimer.setSingleShot(
            True
        )

        self.autoScrollTimer.timeout.connect(
            self.scrollToBottom
        )

        # =================================================
        # THROTTLED STREAMING UI TIMER
        # =================================================

        self.streamingUpdateTimer = QTimer(
            self
        )

        self.streamingUpdateTimer.setSingleShot(
            True
        )

        # Reduced UI update frequency.
        # This prevents Markdown + QLabel + layout
        # recalculation from happening too often.
        self.streamingUpdateTimer.setInterval(
            80
        )

        self.streamingUpdateTimer.timeout.connect(
            self.updateStreamingUI
        )

        self.pendingStreamingChatId = None

        self.setupUI()

        self.scrollArea.verticalScrollBar().valueChanged.connect(
            self.handleScroll
        )

        self.loadChatsToSidebar()

        self.loadModels()

    # =====================================================
    # SIDEBAR ANIMATED PROPERTY
    # =====================================================

    def getAnimatedSidebarWidth(self):

        if self.SideBar is None:

            return 0

        return self.SideBar.width()

    def setAnimatedSidebarWidth(
        self,
        width
    ):

        width = max(
            0,
            min(
                int(width),
                self.sidebarWidth
            )
        )

        centralWidget = self.centralWidget()

        if centralWidget is None:

            return

        centralWidth = centralWidget.width()
        centralHeight = centralWidget.height()

        self.SideBar.setGeometry(
            0,
            0,
            width,
            centralHeight
        )

        self.chatInterface.setGeometry(
            width,
            0,
            max(
                0,
                centralWidth - width
            ),
            centralHeight
        )

    animatedSidebarWidth = Property(
        int,
        getAnimatedSidebarWidth,
        setAnimatedSidebarWidth
    )

    # =====================================================
    # RESIZE
    # =====================================================

    def resizeEvent(
        self,
        event
    ):

        super().resizeEvent(
            event
        )

        if not hasattr(
            self,
            "SideBar"
        ):

            return

        centralWidget = self.centralWidget()

        if centralWidget is None:

            return

        width = self.SideBar.width()

        self.SideBar.setGeometry(
            0,
            0,
            width,
            centralWidget.height()
        )

        self.chatInterface.setGeometry(
            width,
            0,
            max(
                0,
                centralWidget.width() - width
            ),
            centralWidget.height()
        )
        if self.aiStreamingLabel is not None:
            self.aiStreamingLabel.updateGeometry()

        if self.aiBubble is not None:
            self.aiBubble.updateGeometry()

        if hasattr(self, "chatLayout"):
            self.chatLayout.invalidate()
            self.chatLayout.activate()

    # =====================================================
    # SAVE CHAT SCROLL ANCHOR
    # =====================================================

    def saveChatScrollAnchor(self):

        scrollbar = (
            self.scrollArea
            .verticalScrollBar()
        )

        scrollPosition = scrollbar.value()

        self.sidebarWasAtBottom = (
            scrollbar.maximum() - scrollPosition <= 5
        )

        self.scrollAnchorWidget = None
        self.scrollAnchorOffset = 0

        if self.sidebarWasAtBottom:

            return

        anchorPosition = scrollPosition + 10

        for index in range(
            self.chatLayout.count()
        ):

            item = self.chatLayout.itemAt(
                index
            )

            widget = item.widget()

            if widget is None:

                continue

            geometry = widget.geometry()

            if (
                geometry.top()
                <= anchorPosition
                <
                geometry.bottom()
            ):

                self.scrollAnchorWidget = widget

                self.scrollAnchorOffset = (
                    anchorPosition
                    - geometry.top()
                )

                break

    # =====================================================
    # RESTORE CHAT SCROLL ANCHOR
    # =====================================================

    def restoreChatScrollAnchor(self):

        scrollbar = (
            self.scrollArea
            .verticalScrollBar()
        )

        self.chatContainer.layout().activate()

        self.programmaticScroll = True

        try:

            if self.sidebarWasAtBottom:

                scrollbar.setValue(
                    scrollbar.maximum()
                )

                return

            if (
                self.scrollAnchorWidget is not None
                and
                self.scrollAnchorWidget.isVisible()
            ):

                widget = self.scrollAnchorWidget

                newPosition = (
                    widget.geometry().top()
                    + self.scrollAnchorOffset
                    - 10
                )

                newPosition = max(
                    0,
                    min(
                        int(newPosition),
                        scrollbar.maximum()
                    )
                )

                scrollbar.setValue(
                    newPosition
                )

        finally:

            self.programmaticScroll = False

    # =====================================================
    # SETUP UI
    # =====================================================

    def setupUI(self):

        centralWidget = QWidget()

        self.setCentralWidget(
            centralWidget
        )

        centralWidget.setStyleSheet("""
            QWidget {
                background-color: #202020;
            }
        """)

        # =================================================
        # SIDEBAR
        # =================================================

        self.SideBar = QFrame(
            centralWidget
        )

        self.SideBar.setGeometry(
            0,
            0,
            self.sidebarWidth,
            centralWidget.height()
        )

        self.SideBar.setStyleSheet("""
            QFrame {
                background-color: #191919;
            }
        """)

        self.sideBarLayout = QVBoxLayout(
            self.SideBar
        )

        self.sideBarLayout.setContentsMargins(
            10,
            10,
            10,
            12
        )

        self.sideBarLayout.setSpacing(
            8
        )

        # =================================================
        # SIDEBAR HEADER
        # =================================================

        sidebarHeader = QWidget()

        sidebarHeader.setFixedHeight(
            48
        )

        sidebarHeader.setStyleSheet("""
            QWidget {
                background: transparent;
            }
        """)

        sidebarHeaderLayout = QHBoxLayout(
            sidebarHeader
        )

        sidebarHeaderLayout.setContentsMargins(
            4,
            0,
            3,
            0
        )

        sidebarHeaderLayout.setSpacing(
            6
        )

        # -------------------------------------------------
        # SLOWAI LOGO / HEADING
        # -------------------------------------------------

        logoLabel = QLabel(
            "slowAi"
        )

        logoLabel.setAttribute(
            Qt.WA_TranslucentBackground,
            True
        )

        logoLabel.setStyleSheet("""
            QLabel {
                background-color: transparent;
                border: none;
                color: #f2f2f2;
                font-size: 24px;
                font-weight: 700;
                letter-spacing: 0px;
                padding: 0px;
                margin: 0px;
            }
        """)

        logoLabel.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Preferred
        )

        sidebarHeaderLayout.addWidget(
            logoLabel
        )

        sidebarHeaderLayout.addStretch()

        # -------------------------------------------------
        # SIDEBAR TOGGLE
        # -------------------------------------------------

        self.sidebarToggleButton = QPushButton(
            "☰"
        )

        self.sidebarToggleButton.setFixedSize(
            34,
            34
        )

        self.sidebarToggleButton.setCursor(
            Qt.PointingHandCursor
        )

        self.sidebarToggleButton.setToolTip(
            "Hide sidebar"
        )

        self.sidebarToggleButton.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #aaaaaa;
                border: none;
                border-radius: 8px;
                font-size: 19px;
            }

            QPushButton:hover {
                background-color: #303030;
                color: #ffffff;
            }

            QPushButton:pressed {
                background-color: #383838;
            }
        """)

        self.sidebarToggleButton.clicked.connect(
            self.toggleSidebar
        )

        sidebarHeaderLayout.addWidget(
            self.sidebarToggleButton
        )

        self.sideBarLayout.addWidget(
            sidebarHeader
        )

        # =================================================
        # NEW CHAT
        # =================================================

        self.newChatButton = QPushButton(
            "+  New Chat"
        )

        self.newChatButton.setFixedHeight(
            44
        )

        self.newChatButton.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Fixed
        )

        self.newChatButton.setCursor(
            Qt.PointingHandCursor
        )

        self.newChatButton.setStyleSheet("""
            QPushButton {
                background-color: #2b2b2b;
                color: #eeeeee;
                border: 1px solid #383838;
                border-radius: 10px;
                text-align: left;
                padding-left: 13px;
                font-size: 14px;
                font-weight: 500;
            }

            QPushButton:hover {
                background-color: #333333;
                border: 1px solid #444444;
            }

            QPushButton:pressed {
                background-color: #3a3a3a;
            }
        """)

        self.newChatButton.clicked.connect(
            self.createNewChat
        )

        self.sideBarLayout.addWidget(
            self.newChatButton
        )

        # =================================================
        # CHATS LABEL
        # =================================================

        chatsLabel = QLabel(
            "CHATS"
        )

        chatsLabel.setContentsMargins(
            5,
            8,
            0,
            2
        )

        chatsLabel.setStyleSheet("""
            QLabel {
                background: transparent;
                color: #888888;
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 1.5px;
                padding: 0px;
            }
        """)

        self.sideBarLayout.addWidget(
            chatsLabel
        )

        # =================================================
        # CHAT SCROLL AREA
        # =================================================

        self.chatScrollArea = QScrollArea()

        self.chatScrollArea.setWidgetResizable(
            True
        )

        self.chatScrollArea.setFrameShape(
            QFrame.NoFrame
        )

        self.chatScrollArea.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )

        self.chatScrollArea.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded
        )

        self.chatScrollArea.setStyleSheet("""
            QScrollArea {
                background-color: #191919;
                border: none;
            }

            QScrollBar:vertical {
                background-color: #191919;
                width: 6px;
            }

            QScrollBar::handle:vertical {
                background-color: #3d3d3d;
                border-radius: 3px;
                min-height: 30px;
            }

            QScrollBar::handle:vertical:hover {
                background-color: #555555;
            }

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
            }

            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)

        self.chatListWidget = QWidget()

        self.chatListWidget.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Minimum
        )

        self.chatListWidget.setStyleSheet("""
            QWidget {
                background-color: #191919;
            }
        """)

        self.chatListLayout = QVBoxLayout(
            self.chatListWidget
        )

        self.chatListLayout.setContentsMargins(
            0,
            0,
            0,
            0
        )

        self.chatListLayout.setSpacing(
            3
        )

        self.chatListLayout.setAlignment(
            Qt.AlignTop
        )

        self.chatScrollArea.setWidget(
            self.chatListWidget
        )

        self.sideBarLayout.addWidget(
            self.chatScrollArea,
            1
        )

        # =================================================
        # MAIN CHAT INTERFACE
        # =================================================

        self.chatInterface = QWidget(
            centralWidget
        )

        self.chatInterface.setGeometry(
            self.sidebarWidth,
            0,
            max(
                0,
                centralWidget.width() - self.sidebarWidth
            ),
            centralWidget.height()
        )

        mainLayout = QVBoxLayout(
            self.chatInterface
        )

        mainLayout.setContentsMargins(
            0,
            0,
            0,
            0
        )

        mainLayout.setSpacing(
            0
        )

        # =================================================
        # CHAT TOP BAR
        # =================================================

        topBar = QWidget()

        topBar.setFixedHeight(
            52
        )

        topBar.setStyleSheet("""
            QWidget {
                background-color: #202020;
                border-bottom: 1px solid #292929;
            }
        """)

        topBarLayout = QHBoxLayout(
            topBar
        )

        topBarLayout.setContentsMargins(
            12,
            6,
            15,
            6
        )

        topBarLayout.setSpacing(
            8
        )

        self.chatToggleButton = QPushButton(
            "☰"
        )

        self.chatToggleButton.setFixedSize(
            36,
            36
        )

        self.chatToggleButton.setCursor(
            Qt.PointingHandCursor
        )

        self.chatToggleButton.setToolTip(
            "Show sidebar"
        )

        self.chatToggleButton.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #aaaaaa;
                border: none;
                border-radius: 8px;
                font-size: 19px;
            }

            QPushButton:hover {
                background-color: #303030;
                color: #ffffff;
            }

            QPushButton:pressed {
                background-color: #383838;
            }
        """)

        self.chatToggleButton.clicked.connect(
            self.toggleSidebar
        )

        self.chatToggleButton.hide()

        topBarLayout.addWidget(
            self.chatToggleButton
        )

        topBarLayout.addStretch()

        mainLayout.addWidget(
            topBar
        )

        # =================================================
        # CHAT SCROLL
        # =================================================

        self.scrollArea = QScrollArea()

        self.scrollArea.setWidgetResizable(
            True
        )

        self.scrollArea.setFrameShape(
            QFrame.NoFrame
        )

        self.scrollArea.setStyleSheet("""
            QScrollArea {
                background-color: #202020;
                border: none;
            }

            QScrollBar:vertical {
                background-color: #202020;
                width: 9px;
            }

            QScrollBar::handle:vertical {
                background-color: #444444;
                border-radius: 4px;
                min-height: 30px;
            }

            QScrollBar::handle:vertical:hover {
                background-color: #555555;
            }

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
            }

            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)

        self.chatContainer = QWidget()

        self.chatContainer.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Minimum
        )

        self.chatContainer.setStyleSheet("""
            QWidget {
                background-color: #202020;
            }
        """)

        self.chatLayout = QVBoxLayout(
            self.chatContainer
        )

        self.chatLayout.setContentsMargins(
            20,
            10,
            20,
            25
        )

        self.chatLayout.setSpacing(
            14
        )

        self.chatLayout.setAlignment(
            Qt.AlignTop
        )

        self.scrollArea.setWidget(
            self.chatContainer
        )

        mainLayout.addWidget(
            self.scrollArea,
            1
        )

        # =================================================
        # INPUT FRAME
        # =================================================

        inputFrame = QFrame()

        inputFrame.setStyleSheet("""
            QFrame {
                background-color: #202020;
            }
        """)

        inputLayout = QHBoxLayout(
            inputFrame
        )

        inputLayout.setContentsMargins(
            25,
            7,
            25,
            25
        )

        inputLayout.setSpacing(
            10
        )

        # =================================================
        # INPUT
        # =================================================

        self.inputBox = QTextEdit()

        self.inputBox.setPlaceholderText(
            "Ask anything..."
        )

        self.inputBox.setFixedHeight(
            58
        )

        self.inputBox.textChanged.connect(
            self.adjustInputHeight
        )

        self.inputBox.setStyleSheet("""
            QTextEdit {
                background-color: #303030;
                color: white;
                border: 1px solid #444444;
                border-radius: 12px;
                padding: 10px;
                font-size: 18px;
            }

            QTextEdit:focus {
                border: 1px solid #666666;
            }
        """)

        inputLayout.addWidget(
            self.inputBox,
            1
        )

        # =================================================
        # MODEL DROPDOWN
        # =================================================

        self.modelDropdown = QComboBox()

        self.modelDropdown.setFixedHeight(
            58
        )

        self.modelDropdown.setMinimumWidth(
            100
        )

        self.modelDropdown.addItem(
            "llama3.2"
        )

        self.modelDropdown.setStyleSheet("""
            QComboBox {
                background-color: #303030;
                color: white;
                border: 1px solid #444444;
                border-radius: 12px;
                padding-left: 12px;
                padding-right: 12px;
                font-size: 18px;
            }

            QComboBox:hover {
                border: 1px solid #666666;
            }

            QComboBox:focus {
                border: 1px solid #2f80ed;
            }

            QComboBox::drop-down {
                width: 32px;
                border: none;
            }

            QComboBox QAbstractItemView {
                background-color: #303030;
                color: white;
                border: 1px solid #555555;
                selection-background-color: #2f80ed;
                selection-color: white;
                outline: none;
                padding: 4px;
                font-size: 18px;
            }
        """)

        inputLayout.addWidget(
            self.modelDropdown
        )

        # =================================================
        # SEND
        # =================================================

        self.sendButton = QPushButton(
            "Send"
        )

        self.sendButton.setFixedSize(
            85,
            58
        )

        self.sendButton.setCursor(
            Qt.PointingHandCursor
        )

        self.sendButton.setStyleSheet("""
            QPushButton {
                background-color: #2f80ed;
                color: white;
                border: none;
                border-radius: 12px;
                font-size: 18px;
            }

            QPushButton:hover {
                background-color: #3b8ff3;
            }

            QPushButton:pressed {
                background-color: #246dcc;
            }

            QPushButton:disabled {
                background-color: #555555;
                color: #999999;
            }
        """)

        self.sendButton.clicked.connect(
            self.sendMessage
        )

        inputLayout.addWidget(
            self.sendButton
        )

        mainLayout.addWidget(
            inputFrame
        )

    # =====================================================
    # TOGGLE SIDEBAR
    # =====================================================

    def toggleSidebar(self):

        if self.sidebarAnimation is not None:

            if (
                self.sidebarAnimation.state()
                ==
                QPropertyAnimation.Running
            ):

                self.sidebarAnimation.stop()

        self.saveChatScrollAnchor()

        currentWidth = self.SideBar.width()

        if self.sidebarExpanded:

            self.sidebarExpanded = False

            startWidth = currentWidth
            endWidth = 0

            self.chatToggleButton.show()

            self.chatToggleButton.raise_()

            self.sidebarToggleButton.setToolTip(
                "Show sidebar"
            )

        else:

            self.sidebarExpanded = True

            startWidth = currentWidth
            endWidth = self.sidebarWidth

            self.chatToggleButton.hide()

            self.sidebarToggleButton.show()

            self.sidebarToggleButton.setToolTip(
                "Hide sidebar"
            )

        self.sidebarAnimation = QPropertyAnimation(
            self,
            b"animatedSidebarWidth",
            self
        )

        self.sidebarAnimation.setDuration(
            250
        )

        self.sidebarAnimation.setStartValue(
            startWidth
        )

        self.sidebarAnimation.setEndValue(
            endWidth
        )

        self.sidebarAnimation.setEasingCurve(
            QEasingCurve.InOutCubic
        )

        self.sidebarAnimation.finished.connect(
            self.sidebarAnimationFinished
        )

        self.sidebarAnimation.start()

    def sidebarAnimationFinished(self):

        if self.sidebarExpanded:

            self.setAnimatedSidebarWidth(
                self.sidebarWidth
            )

            self.sidebarToggleButton.show()

            self.chatToggleButton.hide()

            self.sidebarToggleButton.setToolTip(
                "Hide sidebar"
            )

        else:

            self.setAnimatedSidebarWidth(
                0
            )

            self.sidebarToggleButton.hide()

            self.chatToggleButton.show()

            self.chatToggleButton.setToolTip(
                "Show sidebar"
            )

        self.restoreChatScrollAnchor()

        self.scrollAnchorWidget = None
        self.scrollAnchorOffset = 0
        self.sidebarWasAtBottom = False

    # =====================================================
    # LOAD SIDEBAR
    # =====================================================

    def loadChatsToSidebar(self):

        self.chatButtons.clear()

        while self.chatListLayout.count():

            item = self.chatListLayout.takeAt(
                0
            )

            widget = item.widget()

            if widget is not None:

                widget.deleteLater()

        chats = self.ChatDb.getAllMessages()

        for chat in chats:

            chat_id = chat["id"]
            name = chat["name"]

            button = ChatButton(
                chat_id,
                name
            )

            self.chatButtons[
                chat_id
            ] = button

            button.clicked.connect(
                lambda checked=False,
                chat_id=chat_id:
                self.loadChat(
                    chat_id
                )
            )

            button.longPressed.connect(
                lambda chat_id=chat_id:
                self.deleteChatFromSidebar(
                    chat_id
                )
            )

            button.setSelected(
                chat_id == self.currentChatId
            )

            if chat_id in self.activeRequests:

                button.startLoading()

            self.chatListLayout.addWidget(
                button
            )

        self.chatListWidget.adjustSize()

    # =====================================================
    # CREATE NEW CHAT
    # =====================================================

    def createNewChat(self):

        self.currentChatId = None

        self.currentChatName = None

        self.messages = []

        self.clearChatUI()

        self.inputBox.clear()

        self.sendButton.setEnabled(
            True
        )

        self.userScrolledUp = False

        self.autoScrollTimer.stop()

        for button in self.chatButtons.values():

            button.setSelected(
                False
            )

        self.inputBox.setFocus()

    # =====================================================
    # LOAD CHAT
    # =====================================================

    def loadChat(
        self,
        chat_id
    ):

        chat = self.ChatDb.getChat(
            chat_id
        )

        if chat is None:

            return

        self.currentChatId = chat["id"]

        self.currentChatName = chat["name"]

        self.messages = chat[
            "messages"
        ].copy()

        for button_id, button in self.chatButtons.items():

            button.setSelected(
                button_id == chat_id
            )

        self.clearChatUI()

        self.userScrolledUp = False

        self.autoScrollTimer.stop()

        for message in self.messages:

            self.addMessage(
                message["role"],
                message["content"],
                scroll=False
            )

        if chat_id in self.activeRequests:

            request = self.activeRequests[
                chat_id
            ]

            partialResponse = request[
                "response"
            ]

            if partialResponse:

                self.showStreamingResponse(
                    partialResponse
                )

            else:

                self.addLoading()

            self.sendButton.setEnabled(
                False
            )

        else:

            self.sendButton.setEnabled(
                True
            )

        QTimer.singleShot(
            50,
            self.scrollToBottom
        )

    # =====================================================
    # DELETE CHAT
    # =====================================================

    def deleteChatFromSidebar(
        self,
        chat_id
    ):

        if chat_id in self.activeRequests:

            QMessageBox.warning(
                self,
                "AI is responding",
                "This chat is currently generating a response.\n\n"
                "Please wait until it finishes before deleting it."
            )

            return

        chat = self.ChatDb.getChat(
            chat_id
        )

        if chat is None:

            return

        answer = QMessageBox.question(
            self,
            "Delete Chat",
            f'Delete "{chat["name"]}"?\n\n'
            "This chat will be permanently deleted.",
            QMessageBox.Yes |
            QMessageBox.No,
            QMessageBox.No
        )

        if answer != QMessageBox.Yes:

            return

        self.ChatDb.deleteChat(
            chat_id
        )

        if self.currentChatId == chat_id:

            self.currentChatId = None

            self.currentChatName = None

            self.messages = []

            self.clearChatUI()

            self.inputBox.clear()

            self.sendButton.setEnabled(
                True
            )

        self.loadChatsToSidebar()

    # =====================================================
    # INPUT HEIGHT
    # =====================================================

    def adjustInputHeight(self):

        documentHeight = (
            self.inputBox
            .document()
            .size()
            .height()
        )

        newHeight = int(
            documentHeight + 25
        )

        newHeight = max(
            58,
            min(
                newHeight,
                150
            )
        )

        self.inputBox.setFixedHeight(
            newHeight
        )

    # =====================================================
    # LOAD MODELS
    # =====================================================

    def loadModels(self):

        self.modelsThread = QThread()

        self.modelsWorker = OllamaWorker()

        self.modelsWorker.moveToThread(
            self.modelsThread
        )

        self.modelsThread.started.connect(
            self.modelsWorker.loadModels
        )

        self.modelsWorker.modelsReceived.connect(
            self.handleModels
        )

        self.modelsWorker.modelsError.connect(
            self.handleModelError
        )

        self.modelsWorker.modelsReceived.connect(
            self.modelsWorker.deleteLater
        )

        self.modelsWorker.modelsError.connect(
            self.modelsWorker.deleteLater
        )

        self.modelsWorker.modelsReceived.connect(
            self.modelsThread.quit
        )

        self.modelsWorker.modelsError.connect(
            self.modelsThread.quit
        )

        self.modelsThread.finished.connect(
            self.modelsThread.deleteLater
        )

        self.modelsThread.finished.connect(
            self.modelsWorkerFinished
        )

        self.modelsThread.start()

    def modelsWorkerFinished(self):

        self.modelsWorker = None

        self.modelsThread = None

    @Slot(list)
    def handleModels(
        self,
        models
    ):

        currentModel = (
            self.modelDropdown.currentText()
        )

        self.modelDropdown.blockSignals(
            True
        )

        self.modelDropdown.clear()

        if models:

            self.modelDropdown.addItems(
                models
            )

            index = (
                self.modelDropdown.findText(
                    currentModel
                )
            )

            if index >= 0:

                self.modelDropdown.setCurrentIndex(
                    index
                )

        else:

            self.modelDropdown.addItem(
                "llama3.2"
            )

        self.modelDropdown.blockSignals(
            False
        )

    @Slot(str)
    def handleModelError(
        self,
        error
    ):

        print(
            "Model loading error:",
            error
        )

    # =====================================================
    # SEND MESSAGE
    # =====================================================

    def sendMessage(self):

        text = (
            self.inputBox
            .toPlainText()
            .strip()
        )

        if not text:

            return

        if (
            self.currentChatId is not None
            and
            self.currentChatId in self.activeRequests
        ):

            return

        model = (
            self.modelDropdown
            .currentText()
        )

        if not model:

            return

        self.userScrolledUp = False

        self.autoScrollTimer.stop()

        self.messages.append({
            "role": "user",
            "content": text
        })

        self.addMessage(
            "user",
            text
        )

        self.inputBox.clear()

        self.sendButton.setEnabled(
            False
        )

        self.addLoading()

        if self.currentChatId is None:

            chatName = (
                text
                .replace(
                    "\n",
                    " "
                )
                .strip()
            )

            if len(chatName) > 40:

                chatName = (
                    chatName[:40]
                    + "..."
                )

            self.currentChatName = (
                chatName
            )

            self.currentChatId = (
                self.ChatDb.createChat(
                    self.currentChatName,
                    self.messages
                )
            )

            self.loadChatsToSidebar()

        else:

            self.ChatDb.updateChat(
                self.currentChatId,
                self.messages
            )

        chat_id = self.currentChatId

        self.startAIRequest(
            chat_id,
            self.messages,
            model
        )

    # =====================================================
    # START AI REQUEST
    # =====================================================

    def startAIRequest(
        self,
        chat_id,
        messages,
        model
    ):

        thread = QThread()

        worker = OllamaWorker(
            chat_id=chat_id,
            messages=messages.copy(),
            model=model
        )

        worker.moveToThread(
            thread
        )

        self.activeRequests[
            chat_id
        ] = {
            "worker": worker,
            "thread": thread,
            "response": ""
        }

        button = self.chatButtons.get(
            chat_id
        )

        if button is not None:

            button.startLoading()

        thread.started.connect(
            worker.run
        )

        worker.chunkReceived.connect(
            self.handleChunkForChat
        )

        worker.finished.connect(
            self.handleAIResponseForChat
        )

        worker.error.connect(
            self.handleErrorForChat
        )

        worker.finished.connect(
            worker.deleteLater
        )

        worker.error.connect(
            worker.deleteLater
        )

        worker.finished.connect(
            thread.quit
        )

        worker.error.connect(
            thread.quit
        )

        thread.finished.connect(
            thread.deleteLater
        )

        thread.finished.connect(
            lambda chat_id=chat_id:
            self.requestFinished(
                chat_id
            )
        )

        thread.start()

    # =====================================================
    # MESSAGE LOADING
    # =====================================================

    def addLoading(self):

        if self.loadingWidget is not None:

            return

        bubble = QFrame()

        bubble.setFixedWidth(
            62
        )

        bubble.setFixedHeight(
            42
        )

        bubble.setStyleSheet("""
            QFrame {
                background-color: #303030;
                border-radius: 10px;
            }
        """)

        layout = QHBoxLayout(
            bubble
        )

        layout.setContentsMargins(
            12,
            5,
            12,
            5
        )

        layout.setSpacing(
            5
        )

        self.loadingLabel = QLabel(
            "●  ●  ●"
        )

        self.loadingLabel.setAlignment(
            Qt.AlignCenter
        )

        self.loadingLabel.setStyleSheet("""
            QLabel {
                color: #aaaaaa;
                background: transparent;
                font-size: 8px;
            }
        """)

        layout.addWidget(
            self.loadingLabel
        )

        self.chatLayout.addWidget(
            bubble
        )

        self.loadingWidget = bubble

        self.loadingDots = 0

        self.loadingTimer = QTimer(
            self
        )

        self.loadingTimer.timeout.connect(
            self.animateLoading
        )

        self.loadingTimer.start(
            350
        )

        if not self.userScrolledUp:

            self.autoScrollTimer.start(
                0
            )

    # =====================================================
    # LOADING ANIMATION
    # =====================================================

    def animateLoading(self):

        if not self.loadingWidget:

            return

        states = [
            "●  ○  ○",
            "○  ●  ○",
            "○  ○  ●",
            "○  ●  ○"
        ]

        self.loadingLabel.setText(
            states[
                self.loadingDots
            ]
        )

        self.loadingDots = (
            self.loadingDots + 1
        ) % len(states)

    # =====================================================
    # REMOVE LOADING
    # =====================================================

    def removeLoading(self):

        if self.loadingTimer:

            self.loadingTimer.stop()

            self.loadingTimer.deleteLater()

            self.loadingTimer = None

        if self.loadingWidget:

            self.loadingWidget.deleteLater()

            self.loadingWidget = None

        self.loadingLabel = None

    # =====================================================
    # HANDLE CHUNK
    # =====================================================

    @Slot(int, str)
    def handleChunkForChat(
        self,
        chat_id,
        chunk
    ):

        request = self.activeRequests.get(
            chat_id
        )

        if request is None:

            return

        request["response"] += chunk

        if self.currentChatId != chat_id:

            return

        self.removeLoading()

        self.pendingStreamingChatId = chat_id

        if not self.streamingUpdateTimer.isActive():

            self.streamingUpdateTimer.start()

    # =====================================================
    # UPDATE STREAMING UI
    # =====================================================

    def updateStreamingUI(self):

        chat_id = self.pendingStreamingChatId

        self.pendingStreamingChatId = None

        if chat_id is None:

            return

        request = self.activeRequests.get(
            chat_id
        )

        if request is None:

            return

        if self.currentChatId != chat_id:

            return

        self.showStreamingResponse(
            request["response"]
        )

    # =====================================================
    # SHOW STREAMING RESPONSE
    # =====================================================

    def showStreamingResponse(
        self,
        response
    ):

        scrollbar = (
            self.scrollArea
            .verticalScrollBar()
        )

        # Remember whether the user was actually
        # near the bottom before changing the content.
        wasAtBottom = (
            scrollbar.maximum() - scrollbar.value()
            <= 40
        )

        if self.aiBubble is None:

            self.aiBubble = QFrame()

            self.aiBubble.setSizePolicy(
                QSizePolicy.Expanding,
                QSizePolicy.Minimum
            )

            self.aiBubble.setStyleSheet("""
                QFrame {
                    background-color: #303030;
                    border-radius: 10px;
                }
            """)

            bubbleLayout = QVBoxLayout(
                self.aiBubble
            )

            bubbleLayout.setContentsMargins(
                14,
                9,
                14,
                8
            )

            bubbleLayout.setSpacing(
                4
            )

            self.aiStreamingLabel = QLabel()

            self.aiStreamingLabel.setWordWrap(
                True
            )

            self.aiStreamingLabel.setTextFormat(
                Qt.RichText
            )

            self.aiStreamingLabel.setTextInteractionFlags(
                Qt.TextSelectableByMouse |
                Qt.LinksAccessibleByMouse
            )

            self.aiStreamingLabel.setOpenExternalLinks(
                True
            )

            self.aiStreamingLabel.setStyleSheet("""
                QLabel {
                    color: #eeeeee;
                    background: transparent;
                    font-size: 18px;
                    padding: 0px;
                    margin: 0px;
                }
            """)

            self.aiStreamingLabel.setSizePolicy(
                QSizePolicy.Ignored,
                QSizePolicy.Minimum
            )

            bubbleLayout.addWidget(
                self.aiStreamingLabel
            )

            self.chatLayout.addWidget(
                self.aiBubble
            )

        html = markdown.markdown(
            response,
            extensions=[
                "extra",
                "tables",
                "nl2br"
            ]
        )

        html = f"""
        <style>

            body {{
                color: #eeeeee;
                font-size: 18px;
                font-family: Arial;
                margin: 0px;
                padding: 0px;
            }}

            p {{
                margin-top: 4px;
                margin-bottom: 8px;
                font-size: 18px;
            }}

            h1 {{
                font-size: 27px;
                margin-top: 8px;
                margin-bottom: 8px;
            }}

            h2 {{
                font-size: 24px;
                margin-top: 8px;
                margin-bottom: 8px;
            }}

            h3 {{
                font-size: 21px;
                margin-top: 8px;
                margin-bottom: 8px;
            }}

            li {{
                font-size: 18px;
            }}

            a {{
                color: #6ea8fe;
                font-size: 18px;
            }}

            code {{
                background-color: #383838;
                color: #eeeeee;
                padding: 2px 5px;
                border-radius: 4px;
                font-family: Consolas;
                font-size: 17px;
            }}

        </style>

        {html}
        """

        self.aiStreamingLabel.setText(
            html
        )
        
        self.aiStreamingLabel.updateGeometry()
        self.aiBubble.updateGeometry()
        self.chatLayout.invalidate()
        # Force the label/document to calculate its actual
        # required height after the HTML changes.
        # self.aiStreamingLabel.adjustSize()

        self.chatLayout.activate()

        self.chatContainer.adjustSize()

        # Only follow the AI if the user was already at
        # the bottom. If they scroll upward, leave them alone.
        if wasAtBottom and not self.userScrolledUp:

            self.autoScrollTimer.start(
                0
            )

    # =====================================================
    # HANDLE USER SCROLL
    # =====================================================

    def handleScroll(
        self,
        value
    ):

        if self.programmaticScroll:

            return

        scrollbar = (
            self.scrollArea
            .verticalScrollBar()
        )

        distanceFromBottom = (
            scrollbar.maximum()
            - value
        )

        if distanceFromBottom <= 40:

            self.userScrolledUp = False

        else:

            self.userScrolledUp = True

            self.autoScrollTimer.stop()

    # =====================================================
    # AI FINISHED
    # =====================================================

    @Slot(int, str)
    def handleAIResponseForChat(
        self,
        chat_id,
        response
    ):

        self.streamingUpdateTimer.stop()

        if self.pendingStreamingChatId == chat_id:

            self.pendingStreamingChatId = None

        request = self.activeRequests.get(
            chat_id
        )

        if request is None:

            return

        if not response.strip():

            response = (
                "The model returned an empty response."
            )

        request["response"] = response

        chat = self.ChatDb.getChat(
            chat_id
        )

        if chat is None:

            return

        messages = chat[
            "messages"
        ].copy()

        messages.append({
            "role": "assistant",
            "content": response
        })

        self.ChatDb.updateChat(
            chat_id,
            messages
        )

        if self.currentChatId == chat_id:

            wasAtBottom = (
                self.scrollArea
                .verticalScrollBar()
                .maximum()
                -
                self.scrollArea
                .verticalScrollBar()
                .value()
                <= 40
            )

            self.removeStreamingBubble()

            self.messages = messages

            self.addMessage(
                "assistant",
                response,
                scroll=False
            )

            self.chatLayout.activate()

            self.chatContainer.adjustSize()

            if wasAtBottom and not self.userScrolledUp:

                self.autoScrollTimer.start(
                    0
                )

    # =====================================================
    # AI ERROR
    # =====================================================

    @Slot(int, str)
    def handleErrorForChat(
        self,
        chat_id,
        error
    ):

        if self.currentChatId == chat_id:

            if self.pendingStreamingChatId == chat_id:

                self.pendingStreamingChatId = None

            self.streamingUpdateTimer.stop()

            self.removeLoading()

            self.removeStreamingBubble()

            self.addMessage(
                "assistant",
                f"Error: {error}"
            )

    # =====================================================
    # REQUEST FINISHED
    # =====================================================

    def requestFinished(
        self,
        chat_id
    ):

        button = self.chatButtons.get(
            chat_id
        )

        if button is not None:

            button.stopLoading()

        self.activeRequests.pop(
            chat_id,
            None
        )

        if self.currentChatId == chat_id:

            self.removeLoading()

            self.removeStreamingBubble()

            self.sendButton.setEnabled(
                True
            )

            self.inputBox.setFocus()

    # =====================================================
    # REMOVE STREAMING BUBBLE
    # =====================================================

    def removeStreamingBubble(self):

        if self.aiBubble:

            self.aiBubble.deleteLater()

            self.aiBubble = None

            self.aiStreamingLabel = None

    # =====================================================
    # ADD MESSAGE
    # =====================================================

    def addMessage(
        self,
        role,
        text,
        scroll=True
    ):

        row = QWidget()

        rowLayout = QHBoxLayout(
            row
        )

        rowLayout.setContentsMargins(
            0,
            0,
            0,
            0
        )

        rowLayout.setSpacing(
            6
        )

        bubble = QFrame()

        bubbleLayout = QVBoxLayout(
            bubble
        )

        bubbleLayout.setContentsMargins(
            14,
            9,
            8,
            7
        )

        bubbleLayout.setSpacing(
            3
        )

        if role == "user":

            bubble.setMaximumWidth(
                720
            )

            bubble.setSizePolicy(
                QSizePolicy.Maximum,
                QSizePolicy.Minimum
            )

            bubble.setStyleSheet("""
                QFrame {
                    background-color: #2f80ed;
                    border-radius: 10px;
                }
            """)

            label = QLabel(
                text
            )

            label.setWordWrap(
                True
            )

            label.setStyleSheet("""
                QLabel {
                    color: white;
                    background: transparent;
                    font-size: 18px;
                }
            """)

            label.setTextInteractionFlags(
                Qt.TextSelectableByMouse
            )

            bubbleLayout.addWidget(
                label
            )

            copyButton = CopyButton()

            copyButton.clicked.connect(
                lambda checked=False:
                self.copyText(
                    text,
                    copyButton
                )
            )

            bubbleLayout.addWidget(
                copyButton,
                alignment=Qt.AlignRight
            )

            rowLayout.addStretch()

            rowLayout.addWidget(
                bubble
            )

        else:

            bubble.setSizePolicy(
                QSizePolicy.Expanding,
                QSizePolicy.Minimum
            )

            bubble.setStyleSheet("""
                QFrame {
                    background-color: #303030;
                    border-radius: 10px;
                }
            """)

            content = AIContent(
                text
            )

            content.setSizePolicy(
                QSizePolicy.Expanding,
                QSizePolicy.Minimum
            )

            bubbleLayout.addWidget(
                content
            )

            copyButton = CopyButton()

            copyButton.clicked.connect(
                lambda checked=False:
                self.copyText(
                    text,
                    copyButton
                )
            )

            bubbleLayout.addWidget(
                copyButton,
                alignment=Qt.AlignRight
            )

            rowLayout.addWidget(
                bubble,
                1
            )

        self.chatLayout.addWidget(
            row
        )

        if role == "user" and scroll:

            self.currentQuestionRow = row

            QTimer.singleShot(
                0,
                self.scrollToCurrentQuestion
            )

    # =====================================================
    # CLEAR CHAT UI
    # =====================================================

    def clearChatUI(self):

        self.streamingUpdateTimer.stop()

        self.pendingStreamingChatId = None

        self.removeLoading()

        self.removeStreamingBubble()

        self.autoScrollTimer.stop()

        while self.chatLayout.count():

            item = self.chatLayout.takeAt(
                0
            )

            widget = item.widget()

            if widget:

                widget.deleteLater()

        self.currentQuestionRow = None

    # =====================================================
    # SCROLL TO QUESTION
    # =====================================================

    def scrollToCurrentQuestion(self):

        if not self.currentQuestionRow:

            return

        self.chatContainer.adjustSize()

        questionPosition = (
            self.currentQuestionRow.mapTo(
                self.chatContainer,
                self.currentQuestionRow.rect().topLeft()
            )
        )

        targetValue = (
            questionPosition.y() - 12
        )

        scrollbar = (
            self.scrollArea.verticalScrollBar()
        )

        targetValue = max(
            0,
            min(
                targetValue,
                scrollbar.maximum()
            )
        )

        self.programmaticScroll = True

        scrollbar.setValue(
            int(targetValue)
        )

        self.programmaticScroll = False

    # =====================================================
    # COPY
    # =====================================================

    def copyText(
        self,
        text,
        button
    ):

        QApplication.clipboard().setText(
            text
        )

        button.setText(
            "Copied!"
        )

        QTimer.singleShot(
            1200,
            lambda:
            button.setText(
                "Copy"
            )
        )

    # =====================================================
    # SCROLL BOTTOM
    # =====================================================

    def scrollToBottom(self):

        scrollbar = (
            self.scrollArea
            .verticalScrollBar()
        )

        # Don't perform another expensive scroll operation
        # if we're already at the bottom.
        if scrollbar.value() == scrollbar.maximum():

            return

        self.programmaticScroll = True

        scrollbar.setValue(
            scrollbar.maximum()
        )

        self.programmaticScroll = False

    # =====================================================
    # CLOSE
    # =====================================================

    def closeEvent(
        self,
        event
    ):

        self.streamingUpdateTimer.stop()

        self.autoScrollTimer.stop()

        if self.loadingTimer is not None:

            self.loadingTimer.stop()

        if self.activeRequests:

            answer = QMessageBox.question(
                self,
                "AI is responding",
                "One or more chats are still generating.\n\n"
                "Are you sure you want to close the application?",
                QMessageBox.Yes |
                QMessageBox.No,
                QMessageBox.No
            )

            if answer != QMessageBox.Yes:

                event.ignore()

                return

            for request in list(
                self.activeRequests.values()
            ):

                thread = request.get(
                    "thread"
                )

                if thread is not None:

                    thread.quit()

        if self.modelsThread is not None:

            self.modelsThread.quit()

        self.ChatDb.close()

        event.accept()


# =========================================================
# RESOURCE PATH
# =========================================================

def resource_path(
    relative_path
):

    if (
        getattr(
            sys,
            "frozen",
            False
        )
        and
        hasattr(
            sys,
            "_MEIPASS"
        )
    ):

        base_path = sys._MEIPASS

    else:

        base_path = os.path.dirname(
            os.path.abspath(
                __file__
            )
        )

    return os.path.join(
        base_path,
        relative_path
    )


# =========================================================
# APPLICATION
# =========================================================

if __name__ == "__main__":

    app = QApplication(
        sys.argv
    )

    app.setStyle(
        "Fusion"
    )

    iconPath = resource_path(
        "icon/icons.ico"
    )

    if os.path.exists(
        iconPath
    ):

        app.setWindowIcon(
            QIcon(
                iconPath
            )
        )

    window = MainWindow()

    window.show()

    sys.exit(
        app.exec()
    )