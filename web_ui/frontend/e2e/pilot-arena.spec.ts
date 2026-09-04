import { test, expect } from '@playwright/test';

const tubResponse = {
  path: '/tmp/tub',
  records: [
    { _index: 0, _timestamp_ms: 0, 'cam/image_array': '0_cam_image_array_.jpg', 'user/angle': 0.1, 'user/throttle': 0.2 },
  ],
  fields: ['cam/image_array', 'user/angle', 'user/throttle'],
  total_physical_records: 1,
};

const summary = {
  angle: { count: 1, mae: 0.15, rmse: 0.15, bias: 0.15, max_abs_error: 0.15 },
  throttle: { count: 1, mae: 0.3, rmse: 0.3, bias: 0.3, max_abs_error: 0.3 },
};

test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    let body: unknown = {};
    if (pathname.endsWith('/tub/load') || pathname.endsWith('/tub/records')) {
      body = tubResponse;
    } else if (pathname.endsWith('/config/load')) {
      body = { config: { DRIVE_LOOP_HZ: 60 } };
    } else if (pathname.endsWith('/arena/model-types')) {
      body = { model_types: ['tflite_linear', 'linear'] };
    } else if (pathname.endsWith('/arena/models')) {
      body = { models: [{ path: '/tmp/DKG-1.tflite', name: 'DKG-1.tflite' }] };
    } else if (pathname.endsWith('/arena/pilots/load')) {
      body = {
        pilot: {
          id: 'pilot-1',
          name: 'DKG-1.tflite',
          model_path: '/tmp/DKG-1.tflite',
          model_type: 'tflite_linear',
          loaded_at: '2026-09-04T00:00:00Z',
        },
      };
    } else if (/\/arena\/pilots\/pilot-1\/predict$/.test(pathname)) {
      body = {
        status: true,
        record_index: 0,
        user: { angle: 0.1, throttle: 0.2 },
        pilot: { angle: 0.25, throttle: 0.5 },
      };
    } else if (pathname.endsWith('/arena/pilots/pilot-1/predictions')) {
      body = {
        points: [
          { index: 0, user_angle: 0.1, user_throttle: 0.2, pilot_angle: 0.25, pilot_throttle: 0.5 },
        ],
        summary,
      };
    }
    await route.fulfill({ json: body });
  });
  await page.goto('/');
});

test('加载 Tub → 加载模型 → 生成曲线 → 展示模型贴合摘要', async ({ page }) => {
  // ConfigLoader：TubLoader 的『加载 Tub』按钮在 config 未加载时禁用
  // （TubLoader.tsx:92 disabled={!config}），真实 UI 流程必须先加载配置。
  await page.getByRole('textbox', { name: '配置路径输入框' }).fill('/tmp/car');
  await page.getByRole('button', { name: '加载配置' }).click();

  // setConfig 会收起侧栏抽屉（useStore.ts:190 activeDrawer: null），
  // 且配置加载后会自动连带加载 <car>/data Tub；等 PA 当前数据卡出现
  // 『Tub: /tmp/tub』即代表 config + auto-tub 均已完成、抽屉已关闭。
  await expect(page.getByText('Tub: /tmp/tub').first()).toBeVisible();

  // 重新打开抽屉，操作 SidePanel 的 TubLoader（真实中文 aria-label）
  await page.getByRole('button', { name: '加载器' }).click();
  await page.getByRole('textbox', { name: 'Tub 路径输入框' }).fill('/tmp/tub');
  await page.getByRole('button', { name: '加载 Tub' }).click();

  // 模型选择器（包在 <label>『模型文件』内）
  const modelSelect = page.getByRole('combobox', { name: '模型文件' });
  await expect(modelSelect.getByRole('option', { name: 'DKG-1.tflite' })).toBeAttached();
  await modelSelect.selectOption('/tmp/DKG-1.tflite');
  await page.getByRole('button', { name: '加载并预测' }).click();

  // predict 返回后 pilot 栏显示 0.250
  await expect(page.getByText('0.250').first()).toBeVisible();

  // 曲线 pilot 选择器无 label；页面有多个 combobox，按 option 文本稳健定位
  const plotSelect = page.getByRole('combobox').filter({
    has: page.getByRole('option', { name: '选择已加载 Pilot' }),
  });
  await plotSelect.selectOption('pilot-1');
  await page.getByRole('button', { name: '生成曲线' }).click();

  await expect(page.getByText('模型贴合摘要（误差 = pilot − 用户）')).toBeVisible();
  await expect(page.getByText('MAE 0.150').first()).toBeVisible();
  await expect(page.getByText('MAE 0.300').first()).toBeVisible();
});
