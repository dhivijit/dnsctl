"""Record controller — populates QTableViews with DNS records (read-only for Phase 1)."""

from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel
from PyQt6.QtWidgets import QMainWindow, QTableView, QHeaderView

from config import SUPPORTED_RECORD_TYPES

# Column definitions for the record table
_COLUMNS = ("Type", "Name", "Content", "TTL", "Priority", "Proxied")


class RecordTableModel(QAbstractTableModel):
    """In-memory table model backed by a list of record dicts."""

    def __init__(self, records: list[dict] | None = None) -> None:
        super().__init__()
        self._records: list[dict] = records or []

    def set_records(self, records: list[dict]) -> None:
        self.beginResetModel()
        self._records = list(records)
        self.endResetModel()

    # -- QAbstractTableModel interface --

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._records)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(_COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return _COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        rec = self._records[index.row()]
        col = index.column()
        if col == 0:
            return rec.get("type", "")
        if col == 1:
            return rec.get("name", "")
        if col == 2:
            return rec.get("content", "")
        if col == 3:
            ttl = rec.get("ttl", 1)
            return "Auto" if ttl == 1 else str(ttl)
        if col == 4:
            return str(rec.get("priority", "")) if rec.get("type") in ("MX", "SRV") else ""
        if col == 5:
            return "Yes" if rec.get("proxied") else "No"
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable


class _TypeFilterProxy(QSortFilterProxyModel):
    """Filters records by DNS type."""

    def __init__(self, record_type: str | None = None) -> None:
        super().__init__()
        self._type = record_type  # None = show all

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if self._type is None:
            return True
        model = self.sourceModel()
        idx = model.index(source_row, 0)
        return model.data(idx) == self._type


class RecordController:
    """Manages the record table views across all tabs."""

    def __init__(self, window: QMainWindow) -> None:
        self._window = window
        self._model = RecordTableModel()

        # Map each tab to its QTableView + proxy
        self._proxies: dict[str, _TypeFilterProxy] = {}
        self._setup_tables()

    def _setup_tables(self) -> None:
        """Wire each tab's QTableView to a filtered proxy model."""
        tab_map: dict[str, str | None] = {
            "recordTableAll": None,
            "recordTableA": "A",
            "recordTableAAAA": "AAAA",
            "recordTableCNAME": "CNAME",
            "recordTableMX": "MX",
            "recordTableTXT": "TXT",
            "recordTableSRV": "SRV",
        }

        for widget_name, rec_type in tab_map.items():
            table: QTableView = getattr(self._window, widget_name, None)
            if table is None:
                continue

            proxy = _TypeFilterProxy(rec_type)
            proxy.setSourceModel(self._model)
            table.setModel(proxy)
            self._proxies[widget_name] = proxy

            # Stretch columns to fill
            header = table.horizontalHeader()
            if header:
                header.setStretchLastSection(True)
                header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    def populate(self, records: list[dict]) -> None:
        """Replace the displayed records."""
        self._model.set_records(records)
