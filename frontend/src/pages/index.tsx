import React from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Collapse from '@mui/material/Collapse';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import TroubleshootIcon from '@mui/icons-material/Troubleshoot';
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import AppShell from '@/app/components/Layout/AppShell';
import { useClaudeTokens } from '@/shared/styles/ThemeContext';

interface Issue {
  id: string;
  title: string;
  severity: 'high' | 'medium';
  symptom: string;
  cause: string;
  fix: string;
  where: string;
}

const ISSUES: Issue[] = [
  {
    id: 'ensurepip',
    title: 'The backend picks an interpreter that cannot build a venv',
    severity: 'high',
    symptom: 'Backend never boots. The log ends on "No module named pip".',
    cause:
      'The host hands run.sh its own interpreter via OPENSWARM_PYTHON, and the packaged build ships that interpreter without ensurepip. Stock run.sh only checks that a candidate is Python 3, so it accepts it, `python3 -m venv` half-succeeds, and the pip install that follows has no pip to run.',
    fix: 'py_usable() now probes `import ensurepip` as well as the version, so an interpreter that cannot produce a working venv is rejected before it is ever used, and the PATH probe continues to the next candidate.',
    where: 'backend/run.sh',
  },
  {
    id: 'sentinel',
    title: 'A broken venv is trusted forever',
    severity: 'high',
    symptom: 'Every boot fails identically, and only a manual rm -rf .venv breaks the loop.',
    cause:
      'run.sh skips the entire venv-create and install block whenever the install sentinel file exists. The sentinel says "we installed once", not "the venv works". Pair a stale sentinel with a hollow venv and the fast path is taken forever, with no route back to the slow path that would have repaired it.',
    fix: 'venv_healthy() requires the interpreter to exist AND `-m pip --version` to succeed. The sentinel is only honoured alongside it, and a venv that fails the probe is deleted and rebuilt from scratch.',
    where: 'backend/run.sh',
  },
  {
    id: 'pythonpath',
    title: 'Installs silently no-op',
    severity: 'high',
    symptom:
      'pip reports success, but imports resolve to versions nobody installed here, and a package listed in pyproject.toml behaves as though it were never added.',
    cause:
      'OpenSwarm exports a PYTHONPATH pointing at the app bundle’s own site-packages. It takes precedence over the venv, so the venv looks fully populated to pip while being nearly empty on disk, and uvicorn later imports the bundle’s fastapi and typeguard rather than the app’s.',
    fix: 'Every venv invocation, both pip and the final uvicorn exec, runs through `env -u PYTHONPATH`, so the venv is the only thing on the import path.',
    where: 'backend/run.sh',
  },
  {
    id: 'warmcache',
    title: 'A failed cache build is copied into every new app',
    severity: 'medium',
    symptom: 'Freshly created apps arrive already broken, in exactly the same way.',
    cause:
      'The warm venv cache is shared across the whole install and keyed on a hash of the template pyproject.toml. backend_init.sh accepts it on a bare `-d` directory test, which a half-written cache from a build that died partway also passes. That corpse is then copied into every app seeded afterwards.',
    fix: 'cache_usable() requires the .populated completion marker AND a real venv interpreter inside it. A partial cache is ignored and the app builds its own venv instead.',
    where: 'backend_init.sh',
  },
  {
    id: 'servemode',
    title: 'Restart parks the app in a static bundle with no backend',
    severity: 'high',
    symptom:
      'The terminal prints "serving the built bundle". The UI loads but every /api call 404s, and restart.sh times out after 30 seconds.',
    cause:
      'Serve-mode saves memory by serving frontend/dist statically instead of spawning vite, and decides the bundle is fresh by comparing its mtime against the newest file under frontend/. That comparison is frontend-only: it never considers whether a backend exists, so an app with a FastAPI backend gets "restarted" into a bundle with nothing behind it. The same path deadlocks restarts, because the sentinel watcher skips runtimes whose process is not running, and a process-less runtime never is, so the request is never consumed.',
    fix: 'frontend/src/.no-serve-mode carries a far-future mtime, so dist can never be newer than every source file and the freshness test is permanently false. Serve-mode is therefore never chosen, and the app always gets a real dev-server runtime that restarts properly.',
    where: 'frontend/src/.no-serve-mode',
  },
  {
    id: 'httpx',
    title: 'An undeclared dependency held up by luck',
    severity: 'medium',
    symptom: 'Nothing today. An ImportError on the day a transitive dependency changes.',
    cause:
      'apps/openswarm_host imports httpx, but stock pyproject.toml never declares it. It resolves only because fastapi[standard] happens to pull it in. Nothing pins that, and nothing would warn before it broke.',
    fix: 'httpx is declared explicitly in [project].dependencies, so it is installed because the app requires it rather than by coincidence.',
    where: 'backend/pyproject.toml',
  },
];

const IssueCard: React.FC<{ issue: Issue; index: number }> = ({ issue, index }) => {
  const c = useClaudeTokens();
  const [open, setOpen] = React.useState(false);

  const sections: [string, string, string][] = [
    ['What you see', issue.symptom, c.text.secondary],
    ['Why it happens', issue.cause, c.text.secondary],
    ['What this template does instead', issue.fix, c.status.success],
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: index * 0.04 }}
    >
      <Box
        sx={{
          bgcolor: c.bg.surface,
          border: `1px solid ${c.border.subtle}`,
          borderRadius: `${c.radius.lg}px`,
          overflow: 'hidden',
        }}
      >
        <Box
          onClick={() => setOpen((v) => !v)}
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1.5,
            px: 2.5,
            py: 2,
            cursor: 'pointer',
            '&:hover': { bgcolor: `${c.text.primary}05` },
          }}
        >
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
              <Typography sx={{ fontWeight: 550, fontSize: '0.97rem', color: c.text.primary }}>
                {issue.title}
              </Typography>
              <Chip
                label={issue.severity}
                size="small"
                sx={{
                  height: 18,
                  fontSize: '0.6rem',
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  bgcolor: issue.severity === 'high' ? `${c.status.error}20` : `${c.text.primary}12`,
                  color: issue.severity === 'high' ? c.status.error : c.text.muted,
                }}
              />
            </Box>
            <Typography
              sx={{ fontSize: '0.78rem', color: c.text.ghost, fontFamily: c.font.mono, mt: 0.4 }}
            >
              {issue.where}
            </Typography>
          </Box>
          <ExpandMoreIcon
            sx={{
              fontSize: 21,
              color: c.text.tertiary,
              transform: open ? 'rotate(180deg)' : 'none',
              transition: c.transition,
            }}
          />
        </Box>

        <Collapse in={open} unmountOnExit>
          <Box sx={{ px: 2.5, pb: 2.5, display: 'flex', flexDirection: 'column', gap: 2 }}>
            {sections.map(([label, body, color]) => (
              <Box key={label}>
                <Typography
                  sx={{
                    fontSize: '0.68rem',
                    fontWeight: 700,
                    letterSpacing: '0.07em',
                    textTransform: 'uppercase',
                    color: c.text.muted,
                    mb: 0.6,
                  }}
                >
                  {label}
                </Typography>
                <Typography sx={{ fontSize: '0.87rem', lineHeight: 1.65, color }}>{body}</Typography>
              </Box>
            ))}
          </Box>
        </Collapse>
      </Box>
    </motion.div>
  );
};

const Home: React.FC = () => {
  const c = useClaudeTokens();
  const navigate = useNavigate();

  return (
    <AppShell>
    <Box sx={{ maxWidth: 900, mx: 'auto', px: { xs: 3, md: 5 }, py: 6 }}>
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <Chip
          label="reference template"
          size="small"
          sx={{
            height: 22,
            fontSize: '0.68rem',
            fontWeight: 600,
            bgcolor: `${c.accent.primary}1A`,
            color: c.accent.primary,
            mb: 2,
          }}
        />
        <Typography
          sx={{
            fontSize: { xs: '2rem', md: '2.5rem' },
            fontWeight: 600,
            color: c.text.primary,
            letterSpacing: '-0.03em',
            lineHeight: 1.15,
          }}
        >
          Why this template exists
        </Typography>
        <Typography
          sx={{ fontSize: '1rem', color: c.text.secondary, mt: 2, lineHeight: 1.7, maxWidth: 660 }}
        >
          A stock OpenSwarm app has six defects in its boot path. Four of them can stop the backend
          from ever starting, and they share a shape: a cheap proxy stands in for something
          expensive. A directory is assumed to be a finished build. A sentinel file is assumed to
          mean a working venv. A frontend timestamp is assumed to describe an app that also has a
          backend. Each check passes while the thing it stands for is broken.
        </Typography>
        <Typography
          sx={{ fontSize: '1rem', color: c.text.secondary, mt: 2, lineHeight: 1.7, maxWidth: 660 }}
        >
          Every fix below replaces one of those proxies with a direct test, and all of them live in
          the workspace. Nothing here patches the OpenSwarm install itself, so the repair travels
          with the app rather than with the machine.
        </Typography>

        <Button
          onClick={() => navigate('/drift')}
          endIcon={<ArrowForwardIcon sx={{ fontSize: 17 }} />}
          startIcon={<TroubleshootIcon sx={{ fontSize: 18 }} />}
          sx={{
            mt: 3.5,
            textTransform: 'none',
            borderRadius: 999,
            px: 2.5,
            py: 1,
            bgcolor: c.accent.primary,
            color: '#fff',
            fontWeight: 550,
            '&:hover': { bgcolor: c.accent.hover },
          }}
        >
          Scan my apps for drift
        </Button>
      </motion.div>

      <Typography
        sx={{
          fontSize: '0.7rem',
          fontWeight: 700,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          color: c.text.muted,
          mt: 6,
          mb: 2,
        }}
      >
        The six defects
      </Typography>

      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
        {ISSUES.map((issue, i) => (
          <IssueCard key={issue.id} issue={issue} index={i} />
        ))}
      </Box>

      <Box
        sx={{
          mt: 5,
          p: 3,
          borderRadius: `${c.radius.lg}px`,
          bgcolor: c.bg.secondary,
          border: `1px solid ${c.border.subtle}`,
        }}
      >
        <Typography sx={{ fontWeight: 600, fontSize: '0.95rem', color: c.text.primary, mb: 1.25 }}>
          Two things this template cannot fix from inside a workspace
        </Typography>
        <Typography sx={{ fontSize: '0.87rem', color: c.text.secondary, lineHeight: 1.65 }}>
          The interpreter fallback chain ends at the system python3. On a machine where that is
          older than 3.10, run.sh will find nothing satisfying requires-python and the backend will
          not boot. A workspace cannot install a Python for itself.
        </Typography>
        <Typography sx={{ fontSize: '0.87rem', color: c.text.secondary, lineHeight: 1.65, mt: 1.5 }}>
          The serve-mode marker depends on its own mtime, and git does not record mtimes. A clone of
          this repo receives a checkout-time mtime, which defeats the workaround silently. The
          template restamps it during backend init for that reason, and the drift page flags a
          marker whose date has regressed rather than only a missing one.
        </Typography>
      </Box>
    </Box>
    </AppShell>
  );
};

export default Home;
