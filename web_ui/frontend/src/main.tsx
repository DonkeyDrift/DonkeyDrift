import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { LanguageProvider } from './i18n'
import './index.css'
import './themes/theme-mus4.css'
import './themes/theme-light.css'
// Apple 深化补充层：Apple 唯一风格的规则体层（原 ui-apple 前缀已拍平，见文件头注释）
import './themes/apple-deep.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LanguageProvider>
      <App />
    </LanguageProvider>
  </StrictMode>,
)
