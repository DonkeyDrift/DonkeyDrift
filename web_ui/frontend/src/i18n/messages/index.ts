import { arena } from './arena';
import { common } from './common';
import { connector } from './connector';
import { drive } from './drive';
import { drivehooks } from './drivehooks';
import { driveviz } from './driveviz';
import { fab } from './fab';
import { trainer } from './trainer';
import { tubeditor } from './tubeditor';
import { tubnav } from './tubnav';

export const MESSAGES: Record<'zh' | 'en', Record<string, string>> = {
  zh: {
    ...arena.zh,
    ...common.zh,
    ...connector.zh,
    ...drive.zh,
    ...drivehooks.zh,
    ...driveviz.zh,
    ...fab.zh,
    ...trainer.zh,
    ...tubeditor.zh,
    ...tubnav.zh,
  },
  en: {
    ...arena.en,
    ...common.en,
    ...connector.en,
    ...drive.en,
    ...drivehooks.en,
    ...driveviz.en,
    ...fab.en,
    ...trainer.en,
    ...tubeditor.en,
    ...tubnav.en,
  },
};
