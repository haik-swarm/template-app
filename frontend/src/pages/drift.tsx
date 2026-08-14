import React from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Collapse from '@mui/material/Collapse';
import CircularProgress from '@mui/material/CircularProgress';
import LinearProgress from '@mui/material/LinearProgress';
import Tooltip from '@mui/material/Tooltip';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CancelIcon from '@mui/icons-material/Cancel';
import RemoveCircleOutlineIcon from '@mui/icons-material/RemoveCircleOutline';
import RefreshIcon from '@mui/icons-material/Refresh';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import { motion } from 'framer-motion';
import AppShell from '@/app/components/Layout/AppShell';
import { useClaudeTokens } from '@/shared/styles/ThemeContext';
import { DRIFT_SCAN_URL } from '@/shared/state/API_ENDPOINTS';

interface Check {
  id: string;
  label: string;
  severity: 'high' | 'medium';
  fix: string;
  state: 'pass' | 'fail' | 'na';
  detail: string;
}

interface AppRow {
  id: string;
  name: string;
  path: string;
  is_self: boolean;
  has_backend: boolean;
  failed: number;
  applicable: number;
  passed: number;
  checks: Check[];
}

interface ScanResult {
  root: string;
  total: number;
  clean: number;
  drifted: number;
  checks: { id: string; label: string; severity: string; fix: string }[];
  apps: AppRow[];
}

const Stat: React.FC<{ value: React.ReactNode; label: string; color: string }> = ({
  value,
  label,
  color,
}) => {
  const c = useClaudeTokens();
  return (
    <Box
      sx={{
        flex: 1,
        minWidth: 130,
        bgcolor: c.bg.surface,
        border: `1px solid ${c.border.subtle}`,
        borderRadius: `${c.radius.lg}px`,
        px: 2.5,
        py: 2,
      }}
    >
      <Typography sx={{ fontSize: '1.9rem', fontWeight: 600, color, lineHeight: 1.1 }}>
        {value}
      </Typography>
      <Typography sx={{ fontSize: '0.78rem', color: c.text.muted, mt: 0.5 }}>{label}</Typography>
    </Box>
  );
};

const AppCard: React.FC<{ app: AppRow }> = ({ app }) => {
  const c = useClaudeTokens();
  const [open, setOpen] = React.useState(false);
  const clean = app.failed === 0;
  // Denominator is the applicable checks, not all six: a frontend-only app is graded on what
  // actually applies to it rather than being credited for checks that never ran.
  const total = app.applicable;
  const passed = app.passed;

  return (
    <Box
      sx={{
        bgcolor: c.bg.surface,
        border: `1px solid ${app.is_self ? c.accent.primary : c.border.subtle}`,
        borderRadius: `${c.radius.lg}px`,
        overflow: 'hidden',
        transition: c.transition,
      }}
    >
      <Box
        onClick={() => setOpen((v) => !v)}
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1.5,
          px: 2.5,
          py: 1.75,
          cursor: 'pointer',
          '&:hover': { bgcolor: `${c.text.primary}05` },
        }}
      >
        {clean ? (
          <CheckCircleIcon sx={{ fontSize: 20, color: c.status.success }} />
        ) : (
          <CancelIcon sx={{ fontSize: 20, color: c.status.error }} />
        )}

        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography
              sx={{
                fontWeight: 550,
                fontSize: '0.95rem',
                color: c.text.primary,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {app.name}
            </Typography>
            {app.is_self && (
              <Chip
                label="this app"
                size="small"
                sx={{
                  height: 19,
                  fontSize: '0.65rem',
                  bgcolor: `${c.accent.primary}1A`,
                  color: c.accent.primary,
                  fontWeight: 600,
                }}
              />
            )}
            {!app.has_backend && (
              <Chip
                label="no backend"
                size="small"
                sx={{
                  height: 19,
                  fontSize: '0.65rem',
                  bgcolor: `${c.text.primary}0D`,
                  color: c.text.muted,
                }}
              />
            )}
          </Box>
          <Typography sx={{ fontSize: '0.72rem', color: c.text.ghost, fontFamily: c.font.mono }}>
            {app.id}
          </Typography>
        </Box>

        <Box sx={{ width: 90, flexShrink: 0 }}>
          <LinearProgress
            variant="determinate"
            value={total === 0 ? 0 : (passed / total) * 100}
            sx={{
              height: 5,
              borderRadius: 999,
              bgcolor: `${c.text.primary}12`,
              '& .MuiLinearProgress-bar': {
                bgcolor: clean ? c.status.success : c.status.error,
                borderRadius: 999,
              },
            }}
          />
          <Typography sx={{ fontSize: '0.68rem', color: c.text.muted, mt: 0.5, textAlign: 'right' }}>
            {passed}/{total} passing
          </Typography>
        </Box>

        <ExpandMoreIcon
          sx={{
            fontSize: 20,
            color: c.text.tertiary,
            transform: open ? 'rotate(180deg)' : 'none',
            transition: c.transition,
          }}
        />
      </Box>

      <Collapse in={open} unmountOnExit>
        <Box sx={{ px: 2.5, pb: 2.5, pt: 0.5, display: 'flex', flexDirection: 'column', gap: 1.25 }}>
          {app.checks.map((chk) => (
            <Box
              key={chk.id}
              sx={{
                display: 'flex',
                gap: 1.25,
                p: 1.5,
                borderRadius: `${c.radius.md}px`,
                bgcolor:
                  chk.state === 'pass'
                    ? c.status.successBg
                    : chk.state === 'fail'
                      ? c.status.errorBg
                      : `${c.text.primary}08`,
              }}
            >
              {chk.state === 'pass' ? (
                <CheckCircleIcon sx={{ fontSize: 17, color: c.status.success, mt: '2px' }} />
              ) : chk.state === 'fail' ? (
                <CancelIcon sx={{ fontSize: 17, color: c.status.error, mt: '2px' }} />
              ) : (
                <RemoveCircleOutlineIcon sx={{ fontSize: 17, color: c.text.ghost, mt: '2px' }} />
              )}
              <Box sx={{ flex: 1 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                  <Typography sx={{ fontSize: '0.85rem', fontWeight: 550, color: c.text.primary }}>
                    {chk.label}
                  </Typography>
                  {chk.state === 'na' && (
                    <Chip
                      label="n/a"
                      size="small"
                      sx={{
                        height: 17,
                        fontSize: '0.6rem',
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        bgcolor: `${c.text.primary}0D`,
                        color: c.text.muted,
                      }}
                    />
                  )}
                  {chk.state === 'fail' && (
                    <Chip
                      label={chk.severity}
                      size="small"
                      sx={{
                        height: 17,
                        fontSize: '0.6rem',
                        fontWeight: 700,
                        textTransform: 'uppercase',
                        bgcolor:
                          chk.severity === 'high' ? `${c.status.error}25` : `${c.text.primary}12`,
                        color: chk.severity === 'high' ? c.status.error : c.text.muted,
                      }}
                    />
                  )}
                </Box>
                <Typography
                  sx={{ fontSize: '0.8rem', color: c.text.secondary, mt: 0.4, lineHeight: 1.5 }}
                >
                  {chk.detail}
                </Typography>
                {chk.state === 'fail' && (
                  <Typography
                    sx={{
                      fontSize: '0.76rem',
                      color: c.text.tertiary,
                      mt: 0.75,
                      fontFamily: c.font.mono,
                      lineHeight: 1.5,
                    }}
                  >
                    Fix: {chk.fix}
                  </Typography>
                )}
              </Box>
            </Box>
          ))}
        </Box>
      </Collapse>
    </Box>
  );
};

const BACKEND_ENABLED = process.env.BACKEND_ENABLED;

const Drift: React.FC = () => {
  const c = useClaudeTokens();
  const [data, setData] = React.useState<ScanResult | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [copied, setCopied] = React.useState(false);

  const runScan = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(DRIFT_SCAN_URL);
      if (!res.ok) throw new Error(`scan failed (${res.status})`);
      setData(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'scan failed');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    if (BACKEND_ENABLED) runScan();
    else {
      setLoading(false);
      setError('This app has no backend enabled, so the scan cannot run.');
    }
  }, [runScan]);

  const copyReport = () => {
    if (!data) return;
    const lines = data.apps
      .filter((a) => a.failed > 0)
      .map(
        (a) =>
          `${a.name} (${a.id}) — ${a.failed} failing\n` +
          a.checks
            .filter((k) => k.state === 'fail')
            .map((k) => `    [${k.severity}] ${k.label}: ${k.detail}`)
            .join('\n'),
      );
    navigator.clipboard.writeText(
      `Drift scan — ${data.drifted}/${data.total} workspaces drifted\n\n${lines.join('\n\n')}`,
    );
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  };

  return (
    <AppShell>
    <Box sx={{ maxWidth: 1000, mx: 'auto', px: { xs: 3, md: 5 }, py: 5 }}>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 2,
          flexWrap: 'wrap',
          mb: 3,
        }}
      >
        <Box>
          <Typography
            sx={{
              fontSize: '1.9rem',
              fontWeight: 600,
              color: c.text.primary,
              letterSpacing: '-0.02em',
            }}
          >
            Detect drift
          </Typography>
          <Typography sx={{ fontSize: '0.92rem', color: c.text.muted, mt: 0.75, maxWidth: 620 }}>
            Grades every app workspace in this OpenSwarm install against the six fixes this template
            carries. Read-only: it reads text files and stats one marker, and never runs or modifies
            anything belonging to another app.
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1 }}>
          {data && (
            <Tooltip title={copied ? 'Copied' : 'Copy failures as text'}>
              <Button
                onClick={copyReport}
                startIcon={<ContentCopyIcon sx={{ fontSize: 16 }} />}
                sx={{
                  textTransform: 'none',
                  borderRadius: 999,
                  color: c.text.secondary,
                  '&:hover': { bgcolor: `${c.text.primary}08` },
                }}
              >
                {copied ? 'Copied' : 'Copy'}
              </Button>
            </Tooltip>
          )}
          <Button
            onClick={runScan}
            disabled={loading || !BACKEND_ENABLED}
            startIcon={<RefreshIcon sx={{ fontSize: 17 }} />}
            sx={{
              textTransform: 'none',
              borderRadius: 999,
              px: 2.25,
              bgcolor: c.accent.primary,
              color: '#fff',
              fontWeight: 550,
              '&:hover': { bgcolor: c.accent.hover },
              '&.Mui-disabled': { bgcolor: `${c.text.primary}12`, color: c.text.ghost },
            }}
          >
            Rescan
          </Button>
        </Box>
      </Box>

      {loading && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 6, justifyContent: 'center' }}>
          <CircularProgress size={20} sx={{ color: c.accent.primary }} />
          <Typography sx={{ color: c.text.muted, fontSize: '0.9rem' }}>
            Scanning workspaces…
          </Typography>
        </Box>
      )}

      {error && !loading && (
        <Box
          sx={{
            p: 2.5,
            borderRadius: `${c.radius.lg}px`,
            bgcolor: c.status.errorBg,
            border: `1px solid ${c.status.error}30`,
          }}
        >
          <Typography sx={{ color: c.status.error, fontWeight: 550, fontSize: '0.9rem' }}>
            {error}
          </Typography>
        </Box>
      )}

      {data && !loading && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
        >
          <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap', mb: 3 }}>
            <Stat value={data.total} label="workspaces scanned" color={c.text.primary} />
            <Stat value={data.clean} label="fully configured" color={c.status.success} />
            <Stat value={data.drifted} label="drifted" color={c.status.error} />
            <Stat
              value={data.apps.reduce((n, a) => n + a.failed, 0)}
              label="failing checks total"
              color={c.text.secondary}
            />
          </Box>

          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
            {data.apps.map((app) => (
              <AppCard key={app.id} app={app} />
            ))}
          </Box>

          <Typography
            sx={{ fontSize: '0.72rem', color: c.text.ghost, mt: 3, fontFamily: c.font.mono }}
          >
            root: {data.root}
          </Typography>
        </motion.div>
      )}
    </Box>
    </AppShell>
  );
};

export default Drift;
