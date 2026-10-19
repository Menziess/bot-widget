#!/usr/bin/env python3
"""Desktop widget: geanimeerd botgezicht plus chatvenster.

Toont een zwevend gezicht met een meldingsstip als de bot op een antwoord of
goedkeuring wacht. Een klik opent het chatvenster; berichten gaan via de
lokale HTTP-API van OpenBot. De code staat in het pakket botwidget/; dit
bestand blijft de naam waarmee de widget wordt gestart.

Vereist: PySide6 (pip install PySide6)
"""

from botwidget.qt_ui.app import main

if __name__ == "__main__":
    main()
