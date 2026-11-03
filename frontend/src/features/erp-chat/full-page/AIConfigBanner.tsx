// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { companyAiStatusText } from '@/features/ai/companyAiStatus';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Settings } from 'lucide-react';

/**
 * Banner shown above the chat panel when the user has not configured an
 * AI provider. Without a usable provider the chat returns a 500-style error
 * and the page feels broken - this banner explains exactly what to do.
 * A configured local runtime (Ollama / vLLM) counts as ready even without a
 * cloud API key, so the banner stays hidden for local-only setups.
 */
export default function AIConfigBanner({ ready, managed }: { ready: boolean | null; managed: boolean }) {
  const { t } = useTranslation();
  if (ready !== false) return null;
  if (managed) return <p role="status" className="m-3 text-sm text-content-secondary">{companyAiStatusText(t, false)}</p>;

  return (
    <div
      className="chat-config-banner"
      style={{
        background: 'var(--chat-surface-1)',
        borderBottom: '1px solid var(--chat-border)',
        padding: '12px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        fontFamily: 'var(--chat-font-body)',
        fontSize: 13,
      }}
    >
      <div
        style={{
          width: 32,
          height: 32,
          borderRadius: '50%',
          background: 'var(--chat-accent)',
          color: '#ffffff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        <Settings size={16} strokeWidth={1.85} />
      </div>
      <div className="chat-config-banner-copy">
        <div style={{ fontWeight: 600, color: 'var(--chat-text-primary)' }}>
          {t('chat.config_banner_title', { defaultValue: 'AI provider not configured' })}
        </div>
        <div style={{ color: 'var(--chat-text-secondary)', marginTop: 2 }}>
          {t('chat.config_banner_desc', {
            defaultValue:
              'Add an API key (Anthropic / OpenAI / Gemini / OpenRouter / Mistral / Groq) to start chatting with your data.',
          })}
        </div>
      </div>
      <Link
        to="/settings"
        style={{
          flexShrink: 0,
          padding: '8px 14px',
          borderRadius: 'var(--chat-radius)',
          background: 'var(--chat-accent)',
          color: '#ffffff',
          textDecoration: 'none',
          fontWeight: 600,
          fontSize: 12,
          whiteSpace: 'nowrap',
        }}
      >
        {t('chat.open_settings', { defaultValue: 'Open Settings' })}
      </Link>
    </div>
  );
}
