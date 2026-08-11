import React, { useEffect, useState } from 'react';
import { getVersion } from '@/services/api';

// Displays the DonkeyDrifter version number in the header, to the left of
// the GitHub link. Styled to match the Drifter Console's muted badge.
export const VersionBadge: React.FC = () => {
  const [version, setVersion] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getVersion()
      .then((v) => {
        if (!cancelled) setVersion(v);
      })
      .catch(() => {
        // Silently ignore — no badge on error.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!version) return null;

  return (
    <span className="text-zinc-500 text-xs uppercase tracking-wider">
      v{version}
    </span>
  );
};
