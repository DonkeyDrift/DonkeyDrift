import React, { useState } from 'react';
import { useTranslation } from '@/i18n';
import { discoverConnectorConsoles } from '@/services/api';

export const EnterButtons: React.FC = () => {
  const { t } = useTranslation();
  const [scanning, setScanning] = useState(false);

  const enterDonkey = () => {
    const host = window.location.hostname;
    window.open(`http://${host}:8090/`, '_blank', 'noopener,noreferrer');
  };

  const enterDrifterConsole = async () => {
    if (scanning) return;
    setScanning(true);
    try {
      const result = await discoverConnectorConsoles();
      if (result.found && result.found.length > 0) {
        window.open(`http://${result.found[0].ip}/`, '_blank', 'noopener,noreferrer');
      } else {
        alert(t('common.enterButtons.consoleNotFound'));
      }
    } catch {
      alert(t('common.enterButtons.consoleNotFound'));
    } finally {
      setScanning(false);
    }
  };

  const cls = 'flex items-center bg-[#5cc8ff] text-[#061019] border border-[#5cc8ff] font-extrabold text-[11px] px-2.5 h-6 rounded-full leading-none transition-colors hover:bg-[#8bdcff] cursor-pointer whitespace-nowrap';

  return (
    <div className="flex items-center gap-2">
      <button type="button" onClick={enterDonkey} title={t('common.enterButtons.donkeyTitle')} className={cls}>
        {t('common.enterButtons.donkey')}
      </button>
      <button type="button" onClick={enterDrifterConsole} disabled={scanning} title={t('common.enterButtons.drifterConsoleTitle')} className={scanning ? `${cls} opacity-60 cursor-wait` : cls}>
        {scanning ? t('common.enterButtons.scanning') : t('common.enterButtons.drifterConsole')}
      </button>
    </div>
  );
};
