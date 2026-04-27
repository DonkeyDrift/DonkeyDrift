import React, { useCallback, useMemo, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/Card';
import { Button } from './ui/Button';
import { Input } from './ui/Input';
import { Database } from 'lucide-react';
import { useStore } from '../store/useStore';

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
    setError,
    clearSelectionRange,
  } = useStore();
  const [filterExpression, setFilterExpression] = useState('');
  const [filterError, setFilterError] = useState<string | null>(null);

  const filteredCount = useMemo(() => records.length, [records.length]);
  const totalCount = useMemo(() => originalRecords.length, [originalRecords.length]);

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

  if (!originalRecords.length) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Database className="w-5 h-5" />
          Data Cleaner
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-2">
          <div className="text-xs text-zinc-400">
            Temporary filter (does not delete records)
          </div>
          <div className="flex gap-2 items-center">
            <Input
              aria-label="Filter expression"
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

        {filterError && (
          <div className="text-xs text-red-400">
            Invalid: {filterError}
          </div>
        )}
      </CardContent>
    </Card>
  );
};