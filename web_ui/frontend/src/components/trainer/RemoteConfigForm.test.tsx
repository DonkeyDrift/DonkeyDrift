import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import { LanguageProvider } from '@/i18n';
import { RemoteConfigForm } from './RemoteConfigForm';

const renderForm = () =>
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
        pythonPath=""
        onPythonPathChange={vi.fn()}
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
