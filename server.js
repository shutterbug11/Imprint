const express    = require('express');
const nodemailer = require('nodemailer');
const cors       = require('cors');
const path       = require('path');

const app = express();
app.use(cors());
app.use(express.json({ limit: '50mb' }));
app.use(express.static(path.join(__dirname)));

app.get('/app', (req, res) => res.sendFile(path.join(__dirname, 'app.html')));
app.get('/studio', (req, res) => res.sendFile(path.join(__dirname, 'studio.html')));
app.get('/landing', (req, res) => res.sendFile(path.join(__dirname, 'index.html')));
app.get('/kinetic', (req, res) => res.sendFile(path.join(__dirname, 'kinetic.html')));

const AI_SERVICE_URL = process.env.AI_SERVICE_URL || 'http://127.0.0.1:8000';

// POST /api/detect-fields — forward template image to Qualcomm EasyOCR AI service
app.post('/api/detect-fields', async (req, res) => {
  const { image } = req.body;
  if (!image) {
    return res.status(400).json({ error: 'Image data is required' });
  }

  try {
    const aiRes = await fetch(`${AI_SERVICE_URL}/detect-fields`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image })
    });

    if (!aiRes.ok) {
      const errText = await aiRes.text();
      return res.status(aiRes.status).json({ error: `AI service error: ${errText}` });
    }

    const data = await aiRes.json();
    res.json(data);
  } catch (err) {
    console.error('Field detection proxy error:', err.message);
    res.status(502).json({
      error: 'Could not connect to Qualcomm EasyOCR AI service at ' + AI_SERVICE_URL + '. Ensure ai-service is running.',
      details: err.message
    });
  }
});

// POST /api/test-smtp  — verify credentials without sending
app.post('/api/test-smtp', async (req, res) => {
  const { smtp } = req.body;
  if (!smtp || !smtp.host || !smtp.user || !smtp.pass) {
    return res.status(400).json({ error: 'host, user and pass are required' });
  }
  try {
    const transporter = nodemailer.createTransport({
      host:   smtp.host,
      port:   parseInt(smtp.port, 10) || 587,
      secure: parseInt(smtp.port, 10) === 465,
      auth:   { user: smtp.user, pass: smtp.pass },
      tls:    { rejectUnauthorized: false },
    });
    await transporter.verify();
    res.json({ ok: true, message: 'SMTP connection successful' });
  } catch (err) {
    console.error('Test error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// POST /api/send-email
// Body: { smtp, to, subject, html, attachmentBase64, filename }
app.post('/api/send-email', async (req, res) => {
  const { smtp, to, subject, html, attachmentBase64, filename } = req.body;

  if (!smtp || !to || !subject || !attachmentBase64) {
    return res.status(400).json({ error: 'Missing required fields' });
  }

  try {
    const transporter = nodemailer.createTransport({
      host:   smtp.host,
      port:   parseInt(smtp.port, 10) || 587,
      secure: parseInt(smtp.port, 10) === 465,
      auth:   { user: smtp.user, pass: smtp.pass },
      tls:    { rejectUnauthorized: false },
    });

    await transporter.sendMail({
      from:     smtp.fromName ? `"${smtp.fromName}" <${smtp.user}>` : smtp.user,
      to,
      subject,
      html,
      priority: 'high',
      headers: {
        'X-Priority':        '1',
        'X-MSMail-Priority': 'High',
        'Importance':        'High',
      },
      attachments: [{
        filename:    filename || 'certificate.png',
        content:     attachmentBase64,
        encoding:    'base64',
        contentType: 'image/png',
      }],
    });

    res.json({ ok: true });
  } catch (err) {
    console.error('Send error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

const PORT = process.env.PORT || 3001;
app.listen(PORT, () => {
  console.log(`Certificate mailer running → http://localhost:${PORT}`);
  console.log('Open http://localhost:' + PORT + '/index.html in your browser.');
});
