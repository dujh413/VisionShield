# Third-party components

VisionShield uses unmodified dynamically loaded third-party libraries. The corresponding license texts are included in LICENSES. This notice does not grant a license to the private VisionShield application source.

- Qt / PySide6 / Shiboken6 6.11.2: LGPL-3.0 option. Core, Gui, Widgets, Network, OpenGL, Svg and image-format libraries remain separate DLLs. Replacement and debugging of these LGPL libraries, including reverse engineering for that purpose, is permitted. Their unmodified corresponding sources are supplied in the separate ThirdParty-Sources asset at the same release.
- GEOS 3.13.1, used through Shapely: LGPL-2.1. Corresponding source is included in the ThirdParty-Sources asset. Shapely itself uses BSD terms.
- YuNet: MIT, with model license included. SFace: Apache-2.0, with model-directory license included.
- RapidOCR and PaddleOCR-derived ONNX text models: Apache-2.0. License notices are included.
- ONNX Runtime: MIT. NumPy and its bundled OpenBLAS: their license notices are included.
- OpenCV and remaining runtime dependencies: license texts copied from the installed distributions used for packaging. Python and the PyInstaller bootloader license with its distribution exception are included.

No Qt Virtual Keyboard, Qt PDF, QML/Quick modules or optional FFmpeg video plugin are needed by this widget-based application; these components are excluded from this release.

Component versions and model SHA256 values are recorded in release-manifest.json. Third-party source origins and archive SHA256 values are recorded in sources.json inside the ThirdParty-Sources asset. Source archives are not executed by the application.

Upstream references:

- https://www.qt.io/development/open-source-lgpl-obligations
- https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/
- https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.2-src/
- https://github.com/libgeos/geos/releases/tag/3.13.1
- https://github.com/opencv/opencv_zoo/tree/26cc381e4d2594bb9f47a26eb8fd96c94a13660d/models
- https://github.com/RapidAI/RapidOCR
- https://github.com/PaddlePaddle/PaddleOCR
