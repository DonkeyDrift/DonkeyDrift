import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/Card';
import { Button } from './ui/Button';
import { Input } from './ui/Input';
import { useStore } from '../store/useStore';
import { deleteRecords, getRecords, restoreRecords } from '../services/api';

const parseFilterExpression = (expression: string) => {
  const trimmed = expression.trim();
  if (!trimmed) {
    return null;
  }

  const match = trimmed.match(/^([a-zA-Z0-9_/]+)\s*(>=|<=|>|<|==)\s*([-+]?\d*\.?\d+)\s*$/);
  if (!match) {
    return null;
  }

  let field = match[1];
  const operator = match[2];
  const value = Number(match[3]);

  if (!Number.isFinite(value)) {
    return null;
  }

  if (!field.includes('/') && field.includes('_')) {
    field = field.replace('_', '/');
  }

  return { field, operator, value };
};

export const DataCleaner: React.FC = () => {
  const {
    originalRecords,
    records,
    setRecords,
    setAllRecords,
    setError,
    selectionStartIndex,
    selectionEndIndex,
    setSelectionRange,
    clearSelectionRange,
  } = useStore();
  const [filterExpression, setFilterExpression] = useState('');
  const [filterError, setFilterError] = useState<string | null>(null);
  const [startIndex, setStartIndex] = useState('');
  const [endIndex, setEndIndex] = useState('');
  const [isConfirmOpen, setIsConfirmOpen] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [actionMode, setActionMode] = useState<'delete' | 'restore'>('delete');

  const filteredCount = useMemo(() => records.length, [records.length]);
  const totalCount = useMemo(() => originalRecords.length, [originalRecords.length]);

  useEffect(() => {
    if (selectionStartIndex != null) {
      setStartIndex(String(selectionStartIndex));
    }
    if (selectionEndIndex != null) {
      setEndIndex(String(selectionEndIndex - 1));
    }
    if (selectionStartIndex == null && selectionEndIndex == null) {
      setStartIndex('');
      setEndIndex('');
    }
  }, [selectionStartIndex, selectionEndIndex]);

  const handleApplyFilter = useCallback(() => {
    setFilterError(null);

    const parsed = parseFilterExpression(filterExpression);
    if (!parsed) {
      setFilterError('Invalid filter expression');
      return;
    }

    const { field, operator, value } = parsed;

    const next = originalRecords.filter((record) => {
      const raw = record[field];
      if (raw == null) {
        return false;
      }

      const numeric = typeof raw === 'number' ? raw : Number(raw);
      if (!Number.isFinite(numeric)) {
        return false;
      }

      switch (operator) {
        case '>':
          return numeric > value;
        case '<':
          return numeric < value;
        case '>=':
          return numeric >= value;
        case '<=':
          return numeric <= value;
        case '==':
          return numeric === value;
        default:
          return false;
      }
    });

    setRecords(next);
    setError(null);
  }, [filterExpression, originalRecords, setRecords, setError]);

  const handleClearFilter = useCallback(() => {
    setFilterError(null);
    setFilterExpression('');
    setRecords(originalRecords);
    clearSelectionRange();
  }, [originalRecords, setRecords, clearSelectionRange]);

  const parseRange = useCallback(() => {
    const start = Number(startIndex);
    const end = Number(endIndex);

    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end < start) {
      return null;
    }

    return { start, end };
  }, [startIndex, endIndex]);

  const handleOpenConfirm = useCallback(
    (mode: 'delete' | 'restore') => {
      const range = parseRange();
      if (!range) {
        setFilterError('Invalid index range');
        return;
      }
      setFilterError(null);
      setActionMode(mode);
      setIsConfirmOpen(true);
    },
    [parseRange]
  );

  const handleOpenDeleteConfirm = useCallback(() => {
    handleOpenConfirm('delete');
  }, [handleOpenConfirm]);

  const handleOpenRestoreConfirm = useCallback(() => {
    handleOpenConfirm('restore');
  }, [handleOpenConfirm]);

  const handleCancelConfirm = useCallback(() => {
    setIsConfirmOpen(false);
  }, []);

  const handleConfirmAction = useCallback(async () => {
    const range = parseRange();
    if (!range) {
      setFilterError('Invalid index range');
      return;
    }

    setSelectionRange(range.start, range.end + 1);

    const indexes: number[] = [];
    for (let i = range.start; i <= range.end; i += 1) {
      indexes.push(i);
    }

    if (indexes.length === 0) {
      setFilterError('No records in selected range');
      return;
    }

    setIsProcessing(true);
    try {
      if (actionMode === 'delete') {
        await deleteRecords(indexes);
      } else {
        await restoreRecords(indexes);
      }

      const data = await getRecords(0, 100000);
      const nextRecords = data.records || [];
      setAllRecords(nextRecords);
      setIsConfirmOpen(false);
      setFilterError(null);
    } catch {
      setFilterError(actionMode === 'delete' ? 'Delete failed' : 'Restore failed');
    } finally {
      setIsProcessing(false);
    }
  }, [actionMode, parseRange, setAllRecords, setSelectionRange]);

  if (!originalRecords.length) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Data Cleaner</span>
          <span className="text-xs text-zinc-400">
            Filtered{' '}
            <span className="font-mono">
              {filteredCount} / {totalCount}
            </span>
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <label className="text-xs text-zinc-400">
            Filter expression
          </label>
          <div className="flex gap-2">
            <Input
              aria-label="Filter expression input"
              placeholder="e.g. user_throttle>0.1"
              value={filterExpression}
              onChange={(e) => setFilterExpression(e.target.value)}
            />
            <Button onClick={handleApplyFilter}>
              Apply filter
            </Button>
            <Button variant="secondary" onClick={handleClearFilter}>
              Clear
            </Button>
          </div>
        </div>

        <div className="space-y-2">
          <div className="text-xs text-zinc-400">
            Filtered record count
          </div>
          <div className="text-sm text-zinc-200">
            {filteredCount} of {totalCount}
          </div>
        </div>

        <div className="space-y-2">
          <div className="text-xs text-zinc-400">
            Index range to delete / restore
          </div>
          <div className="flex gap-2 items-center">
            <Input
              aria-label="Start index"
              placeholder="Start"
              value={startIndex}
              onChange={(e) => setStartIndex(e.target.value)}
              className="w-24"
            />
            <span className="text-xs text-zinc-400">to</span>
            <Input
              aria-label="End index"
              placeholder="End"
              value={endIndex}
              onChange={(e) => setEndIndex(e.target.value)}
              className="w-24"
            />
            <Button variant="danger" onClick={handleOpenDeleteConfirm}>
              Delete
            </Button>
            <Button variant="secondary" onClick={handleOpenRestoreConfirm}>
              Restore
            </Button>
          </div>
        </div>

        {filterError && (
          <div className="text-xs text-red-400">
            Invalid: {filterError}
          </div>
        )}

        {isConfirmOpen && (
          <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60">
            <div className="rounded-lg bg-zinc-900 border border-zinc-700 p-6 w-full max-w-sm space-y-4">
              <div className="text-sm font-semibold">
                {actionMode === 'delete' ? 'Confirm deletion' : 'Confirm restore'}
              </div>
              <div className="text-xs text-zinc-300">
                {actionMode === 'delete'
                  ? 'This will delete records in the selected index range. This action cannot be undone. Continue?'
                  : 'This will restore records in the selected index range back into the active dataset. Continue?'}
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="secondary" onClick={handleCancelConfirm} disabled={isProcessing}>
                  Cancel
                </Button>
                <Button variant="danger" onClick={handleConfirmAction} disabled={isProcessing}>
                  {isProcessing ? (actionMode === 'delete' ? 'Deleting...' : 'Restoring...') : 'Confirm'}
                </Button>
              </div>
              <div className="text-[11px] text-emerald-400">
                {actionMode === 'delete'
                  ? 'Success: Records in range will be removed from the tub and chart after confirmation.'
                  : 'Success: Records in range will be restored into the tub and chart after confirmation.'}
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
