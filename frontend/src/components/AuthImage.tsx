import { useEffect, useState } from 'react';
import { api } from '../services/api';

interface Props {
  imgId: string;
  alt: string;
  className?: string;
  style?: React.CSSProperties;
  onClick?: (e: React.MouseEvent) => void;
  conversationId?: string;
}

/**
 * Loads an image from the authenticated API and renders it as a blob URL.
 * Required because <img src=...> cannot send Authorization headers.
 */
export default function AuthImage({ imgId, alt, className, style, onClick, conversationId }: Props) {
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let revoked = false;
    let createdUrl: string | null = null;

    (async () => {
      try {
        const params: any = {};
        if (conversationId) params.conversation_id = conversationId;
        const res = await api.get(`/images/${imgId}`, { params, responseType: 'blob' });
        if (revoked) return;
        createdUrl = URL.createObjectURL(res.data);
        setSrc(createdUrl);
      } catch (e) {
        setError(true);
      }
    })();

    return () => {
      revoked = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [imgId, conversationId]);

  if (error) {
    return (
      <div className={className} style={style}>
        <div className="text-xs text-slate-400 text-center p-2">Image unavailable</div>
      </div>
    );
  }

  if (!src) {
    return (
      <div className={className} style={style}>
        <div className="animate-pulse bg-slate-200 w-full h-full rounded" />
      </div>
    );
  }

  return (
    <img
      src={src}
      alt={alt}
      className={className}
      style={style}
      onClick={onClick}
    />
  );
}
