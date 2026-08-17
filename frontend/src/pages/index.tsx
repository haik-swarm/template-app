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

interface Decision {
  id: string;
  title: string;
  where: string;
  patched: string;
  default: string;
  why: string;
}

interface Shared {
  id: string;
  title: string;
  where: string;
  what: string;
  why: string;
}

const DECISIONS: Decision[] = [
  {
    id: 'ensurepip',
    title: 'How run.sh picks an interpreter',
    where: 'backend/run.sh',
    patched:
      'py_usable() probes `import ensurepip` as well as the version, so an interpreter that cannot produce a working venv is rejected and the PATH probe continues to the next candidate.',
    default:
      'A bare `sys.version_info[0]==3` probe. Anything calling itself Python 3 is accepted, and that is the whole test.',
    why: 'The host hands run.sh its own interpreter via OPENSWARM_PYTHON, and the packaged build ships that interpreter without ensurepip. Under Default V1.7.8-exp.8+ it is accepted, `python3 -m venv` half-succeeds, and the install that follows has no pip to run. Patched V1.7.6 spends an extra subprocess to find that out first.',
  },
  {
    id: 'sentinel',
    title: 'What the install-skip sentinel is trusted to mean',
    where: 'backend/run.sh',
    patched:
      'venv_healthy() requires the interpreter to exist AND `-m pip --version` to succeed. The sentinel is only honoured alongside it, and a venv that fails the probe is deleted and rebuilt.',
    default:
      '`if [[ -d "$VENV_DIR" && -f "$SENTINEL" ]]` and nothing behind it. The file existing is proof enough to skip the venv-create and install block.',
    why: 'The sentinel records "we installed once", not "the venv works". Pair a stale sentinel with a hollow venv and Default V1.7.8-exp.8+ takes the fast path forever, with no route back to the slow path that would have repaired it. Patched V1.7.6 pays a pip probe on every boot to keep that route open.',
  },
  {
    id: 'pythonpath',
    title: 'Whether PYTHONPATH reaches pip and uvicorn',
    where: 'backend/run.sh',
    patched:
      'Every venv invocation, both pip and the final exec of uvicorn, runs through `env -u PYTHONPATH`, so the venv is the only thing on the import path.',
    default:
      'uvicorn is launched straight off `"$VENV_PY"`, with whatever PYTHONPATH the host exported still intact.',
    why: 'OpenSwarm exports a PYTHONPATH pointing at the app bundle’s own site-packages, and it takes precedence over the venv. Under Default V1.7.8-exp.8+ the venv looks fully populated to pip while being nearly empty on disk, and uvicorn imports the bundle’s fastapi and typeguard rather than the app’s. A third spelling also exists in the wild: a single `unset PYTHONPATH` near the top of the script, which clears the variable for every later command. The scanner grades that as satisfying this check, because behaviourally it does, but no direction button writes it, so an app carrying it sits on neither side of this decision.',
  },
  {
    id: 'servemode',
    title: 'Whether serve-mode can claim the app',
    where: 'frontend/src/.no-serve-mode',
    patched:
      'The marker exists and carries a far-future mtime (2038-01-01), so dist can never be newer than every source file, the freshness test is permanently false, and the app always gets a real dev-server runtime.',
    default: 'No marker at all. Serve-mode is free to decide the bundle is fresh.',
    why: 'Serve-mode saves memory by serving frontend/dist statically instead of spawning vite, and decides freshness by comparing dist’s mtime against the newest file under frontend/. That comparison is frontend-only: it never asks whether a backend exists, so an app with a FastAPI backend gets restarted into a bundle with nothing serving /api. The same path deadlocks restart.sh, because the sentinel watcher skips runtimes whose process is not running, and a process-less runtime never is.',
  },
];

const SHARED: Shared[] = [
  {
    id: 'warmcache',
    title: 'The warm cache is gated on a completion marker',
    where: 'backend_init.sh',
    what: 'cache_usable() requires the .populated marker AND a real venv interpreter inside the cache. A partial cache is ignored and the app builds its own venv instead.',
    why: 'The warm venv cache is shared across the whole install and keyed on a hash of the template pyproject.toml. A bare `-d` directory test also passes for a half-written cache left behind by a build that died partway, and that corpse then gets copied into every app seeded afterwards. Neither variant wants that, so there is nothing to choose here.',
  },
  {
    id: 'httpx',
    title: 'httpx is declared rather than inherited',
    where: 'backend/pyproject.toml',
    what: 'httpx appears explicitly in [project].dependencies, so it is installed because the app requires it.',
    why: 'apps/openswarm_host imports httpx, but stock pyproject.toml never declares it. It resolves only because fastapi[standard] happens to pull it in transitively. Nothing pins that, and nothing would warn before it broke. Again, not a choice: both variants declare it.',
  },
];

const Section: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => {
  const c = useClaudeTokens();
  return (
    <>
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
        {label}
      </Typography>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>{children}</Box>
    </>
  );
};

const Card: React.FC<{
  title: string;
  where: string;
  chip: { text: string; color: string };
  index: number;
  sections: [string, string][];
}> = ({ title, where, chip, index, sections }) => {
  const c = useClaudeTokens();
  const [open, setOpen] = React.useState(false);

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
                {title}
              </Typography>
              <Chip
                label={chip.text}
                size="small"
                sx={{
                  height: 18,
                  fontSize: '0.6rem',
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  bgcolor: `${chip.color}20`,
                  color: chip.color,
                }}
              />
            </Box>
            <Typography
              sx={{ fontSize: '0.78rem', color: c.text.ghost, fontFamily: c.font.mono, mt: 0.4 }}
            >
              {where}
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
            {sections.map(([label, body]) => (
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
                <Typography sx={{ fontSize: '0.87rem', lineHeight: 1.65, color: c.text.secondary }}>
                  {body}
                </Typography>
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
            label="reference"
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
            Two ways to spell the boot path
          </Typography>
          <Typography
            sx={{ fontSize: '1rem', color: c.text.secondary, mt: 2, lineHeight: 1.7, maxWidth: 660 }}
          >
            An OpenSwarm backend boots through four decision points, and at each one there are two
            coherent answers. Patched V1.7.6 checks the expensive thing directly: it probes the
            interpreter, probes the venv, strips the environment per command, and pins the
            serve-mode marker out of reach. Default V1.7.8-exp.8+ takes the cheap proxy at each of
            those points
            and boots faster for it.
          </Typography>
          <Typography
            sx={{ fontSize: '1rem', color: c.text.secondary, mt: 2, lineHeight: 1.7, maxWidth: 660 }}
          >
            Neither side is the correct one, and the drift page converts an app in either direction.
            What it flags is an app answering some points one way and the rest the other, because
            that combination is nobody&rsquo;s design: it is what a partial edit, a bad merge, or a
            half-finished conversion leaves behind. An app matching neither spelling at a given
            point reads as unknown rather than wrong.
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

        <Section label="The four decision points">
          {DECISIONS.map((d, i) => (
            <Card
              key={d.id}
              title={d.title}
              where={d.where}
              chip={{ text: 'decides variant', color: c.accent.primary }}
              index={i}
              sections={[
                ['What Patched V1.7.6 writes', d.patched],
                ['What Default V1.7.8-exp.8+ writes', d.default],
                ['Why they differ', d.why],
              ]}
            />
          ))}
        </Section>

        <Section label="Two things both variants do">
          {SHARED.map((s, i) => (
            <Card
              key={s.id}
              title={s.title}
              where={s.where}
              chip={{ text: 'shared', color: c.status.success }}
              index={i}
              sections={[
                ['What both variants write', s.what],
                ['Why it is not a choice', s.why],
              ]}
            />
          ))}
        </Section>

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
            Two things no variant can fix from inside a workspace
          </Typography>
          <Typography sx={{ fontSize: '0.87rem', color: c.text.secondary, lineHeight: 1.65 }}>
            The interpreter fallback chain ends at the system python3. On a machine where that is
            older than 3.10, run.sh will find nothing satisfying requires-python and the backend
            will not boot under either spelling. A workspace cannot install a Python for itself.
          </Typography>
          <Typography sx={{ fontSize: '0.87rem', color: c.text.secondary, lineHeight: 1.65, mt: 1.5 }}>
            Patched V1.7.6&rsquo;s serve-mode marker depends on its own mtime, and git does not record
            mtimes. A clone receives a checkout-time mtime, which defeats the marker silently while
            leaving the file in place. Nothing restamps it automatically, so the drift page reads a
            marker whose date has regressed as neither variant rather than as Patched V1.7.6, and
            converting to Patched V1.7.6 is what rewrites the timestamp.
          </Typography>
        </Box>
      </Box>
    </AppShell>
  );
};

export default Home;
