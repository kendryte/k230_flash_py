# k230_flash_gui

## 环境

- Python 3.9
- PySide6

## 开发

- 国际化

```shell
# 更新翻译文件（包含所有需要翻译的Python文件）
$ pyside6-lupdate main.py single_flash.py advanced_settings.py batch_flash.py -ts english.ts

# 使用Qt Linguist编辑翻译
$ pyside6-linguist english.ts
# 在菜单中选择发布为english.qm，或者使用命令行：
$ pyside6-lrelease english.ts -qm english.qm
```

- 引入资源文件

# 然后将english.qm配置到resources.qrc中

<qresource prefix="/translations">
    <file>english.qm</file>
  </qresource>
# 最后重新生成resources_rc.py
$ pyside6-rcc resources.qrc -o resources_rc.py
```

## 打包

### 准备环境

```bash
# 进入 GUI 目录
cd src\gui

# 确保安装了所需依赖
pip install pyinstaller
pip install -e ../../  # 安装项目本身

# 使用 spec 文件打包
pyinstaller k230_flash_gui.spec

# 或者如果需要清理之前的构建
pyinstaller --clean k230_flash_gui.spec
```
