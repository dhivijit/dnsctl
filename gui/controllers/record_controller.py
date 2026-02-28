"""Record controller — populates QTableViews with DNS records, supports CRUD."""

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

    @property
    def records(self) -> list[dict]:
        """Return the current records list."""
        return list(self._model._records)

    def get_selected_record(self) -> dict | None:
        """Return the selected record from the currently visible table, or None."""
        # Find which table is currently showing
        tabs = self._window.recordTabs
        current_widget = tabs.currentWidget()
        if current_widget is None:
            return None

        # Find the QTableView inside the current tab
        table: QTableView | None = None
        for child in current_widget.findChildren(QTableView):
            table = child
            break
        if table is None:
            return None

        indexes = table.selectionModel().selectedRows()
        if not indexes:
            return None

        # Map proxy index → source index
        proxy_idx = indexes[0]
        proxy_model = table.model()
        if isinstance(proxy_model, QSortFilterProxyModel):
            source_idx = proxy_model.mapToSource(proxy_idx)
        else:
            source_idx = proxy_idx

        row = source_idx.row()
        if 0 <= row < len(self._model._records):
            return self._model._records[row]
        return None

    def connect_selection_changed(self, callback) -> None:
        """Connect selection-changed signals from all tables to *callback*."""
        for widget_name in self._proxies:
            table: QTableView = getattr(self._window, widget_name, None)
            if table is not None and table.selectionModel():
                table.selectionModel().selectionChanged.connect(
                    lambda _sel, _desel, cb=callback: cb()
                )

    def add_record(self, record: dict) -> None:
        """Append a record to the in-memory list."""
        self._model.beginInsertRows(QModelIndex(), len(self._model._records), len(self._model._records))
        self._model._records.append(record)
        self._model.endInsertRows()

    def update_record(self, old_record: dict, new_record: dict) -> None:
        """Replace a record in-place by identity (id or reference)."""
        for i, r in enumerate(self._model._records):
            if r is old_record or (r.get('id') and r.get('id') == old_record.get('id')):
                self._model._records[i] = new_record
                tl = self._model.index(i, 0)
                br = self._model.index(i, self._model.columnCount() - 1)
                self._model.dataChanged.emit(tl, br)
                return

    def delete_record(self, record: dict) -> None:
        """Remove a record from the in-memory list."""
        for i, r in enumerate(self._model._records):
            if r is record or (r.get('id') and r.get('id') == record.get('id')):
                self._model.beginRemoveRows(QModelIndex(), i, i)
                self._model._records.pop(i)
                self._model.endRemoveRows()
                return
