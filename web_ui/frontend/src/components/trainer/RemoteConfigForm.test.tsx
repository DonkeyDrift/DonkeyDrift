import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import { LanguageProvider } from '@/i18n';
import { RemoteConfigForm } from './RemoteConfigForm';

const renderForm = (props = {}) =>
  render(
    <LanguageProvider>
      <RemoteConfigForm
        host=""
        onHostChange={vi.fn()}
        user=""
        onUserChange={vi.fn()}
        password=""
        onPasswordChange={vi.fn()}
        remoteDirBase=""
        onRemoteDirBaseChange={vi.fn()}
        modelName=""
        onModelNameChange={vi.fn()}
        modelType="linear"
        onModelTypeChange={vi.fn()}
        pythonPath=""
        onPythonPathChange={vi.fn()}
        {...props}
      />
    </LanguageProvider>,
  );

describe('RemoteConfigForm 密码管理器抑制', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('密码框声明 new-password 并带密码管理器忽略属性，不触发保存/强密码提示', () => {
    const { container } = renderForm();
    const pwd = container.querySelector('input[type="password"]');
    expect(pwd).not.toBeNull();
    expect(pwd).toHaveAttribute('autocomplete', 'new-password');
    expect(pwd).toHaveAttribute('data-1p-ignore', 'true');
    expect(pwd).toHaveAttribute('data-lpignore', 'true');
    expect(pwd).toHaveAttribute('data-form-type', 'other');
  });

  it('主机 IP 与用户名框 autocomplete=off，不被当作登录表单字段', () => {
    const { container } = renderForm();
    const grid = container.querySelector('.grid');
    const textInputs = grid ? Array.from(grid.querySelectorAll('input[type="text"]')) : [];
    expect(textInputs).toHaveLength(2);
    for (const el of textInputs) {
      expect(el).toHaveAttribute('autocomplete', 'off');
      expect(el).toHaveAttribute('autocapitalize', 'none');
      expect(el).toHaveAttribute('spellcheck', 'false');
    }
  });
});

describe('RemoteConfigForm 模型配置（compact=我这台电脑模式）', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('compact 模式仍显示模型名称输入框，输入触发 onModelNameChange', () => {
    const onModelNameChange = vi.fn();
    const { container } = renderForm({ compact: true, onModelNameChange });
    const inputs = Array.from(container.querySelectorAll('input[type="text"]'));
    // host/user 带 autocomplete=off，keyPath 的 placeholder 是 ~/.ssh/id_rsa；
    // 模型名称是 compact 模式下唯一「无 autocomplete 且非 keyPath」的文本输入
    const modelInput = inputs.find(
      (el) => !el.hasAttribute('autocomplete') &&
        el.getAttribute('placeholder') !== '~/.ssh/id_rsa',
    ) as HTMLInputElement;
    expect(modelInput).toBeTruthy();
    fireEvent.change(modelInput, { target: { value: 'pilot_mac' } });
    expect(onModelNameChange).toHaveBeenCalledWith('pilot_mac');
  });

  it('compact 模式显示模型类型下拉，选择触发 onModelTypeChange', () => {
    const onModelTypeChange = vi.fn();
    const { container } = renderForm({ compact: true, onModelTypeChange });
    const select = container.querySelector('select') as HTMLSelectElement | null;
    expect(select).not.toBeNull();
    expect(select!.value).toBe('linear');
    const options = Array.from(select!.options).map((o) => o.value);
    expect(options).toEqual(
      expect.arrayContaining(['linear', 'categorical', 'rnn', 'imu', 'behavior', 'localizer', '3d']));
    fireEvent.change(select!, { target: { value: 'categorical' } });
    expect(onModelTypeChange).toHaveBeenCalledWith('categorical');
  });

  it('compact 模式不显示远程目录/Python 路径（由环境探测自动填）', () => {
    const { container } = renderForm({ compact: true });
    const text = container.textContent || '';
    expect(text).not.toContain('~/projects');
  });
});
