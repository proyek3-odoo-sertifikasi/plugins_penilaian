from odoo import models, fields, api


class LspDetailJawaban(models.Model):
    """Detail Jawaban untuk setiap soal pada hasil asesmen

    - PG: nilai dan is_correct dihitung otomatis
    - Essay/Praktik: nilai diinput oleh asesor
    """
    _name = "lsp.detail.jawaban"
    _description = "Detail Jawaban Hasil Asesmen"

    hasil_asesmen_id = fields.Many2one("lsp.hasil.asesmen", string="Hasil Asesmen", ondelete="cascade")
    # Jika modul bank soal tidak tersedia, simpan referensi soal sebagai teks
    soal_ref = fields.Char(string="Ref Soal")
    tipe_soal = fields.Selection([
        ("pg", "PG"),
        ("essay", "Essay"),
        ("praktik", "Praktik"),
    ], string="Tipe Soal", required=True, default="pg")

    jawaban_asesi = fields.Text(string="Jawaban Asesi")
    jawaban_benar = fields.Text(string="Kunci Jawaban")

    nilai = fields.Float(string="Nilai", digits=(6,2), help="Untuk PG akan dihitung otomatis (0 atau 100)")
    is_correct = fields.Boolean(string="Benar", compute="_compute_correct", store=True)

    @api.depends("jawaban_asesi", "jawaban_benar", "tipe_soal")
    def _compute_correct(self):
        for rec in self:
            if rec.tipe_soal == "pg":
                # bandingkan jawaban sederhana (case-insensitive, strip)
                a = (rec.jawaban_asesi or "").strip().lower()
                b = (rec.jawaban_benar or "").strip().lower()
                rec.is_correct = bool(a and b and a == b)
                rec.nilai = 100.0 if rec.is_correct else 0.0
            else:
                rec.is_correct = False
                # untuk essay/praktik nilai diisi manual oleh asesor; jangan override
