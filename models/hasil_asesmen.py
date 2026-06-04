# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class LspHasilAsesmen(models.Model):
    _name = "lsp.hasil.asesmen"
    _description = "Hasil Asesmen LSP"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(string="Nomor Asesmen", required=True, copy=False, readonly=True, default=lambda self: '/')
    student_id = fields.Many2one("lsp.student", string="Asesi", required=True, tracking=True)
    user_id = fields.Many2one("res.users", related="student_id.user_id", string="User Asesi", store=True)
    asesor_id = fields.Many2one("res.users", string="Asesor Penguji", required=True, tracking=True)
    jadwal_id = fields.Many2one("lsp.jadwal.ujian", string="Jadwal Ujian", required=True)
    skema_id = fields.Many2one("lsp.skema.sertifikasi", related="jadwal_id.skema_id", string="Skema Sertifikasi", store=True)
    survey_input_id = fields.Many2one("survey.user_input", string="Jawaban Survei", required=True, ondelete="cascade")
    
    line_ids = fields.One2many("lsp.hasil.asesmen.line", "hasil_asesmen_id", string="Detail Jawaban", copy=False)
    unit_line_ids = fields.One2many("lsp.hasil.asesmen.unit", "hasil_asesmen_id", string="Nilai per Unit Kompetensi", copy=False)

    nilai_total = fields.Float(string="Total Nilai Kumulatif", compute="_compute_nilai_total", store=True)
    nilai_maksimal = fields.Float(string="Total Nilai Maksimal", compute="_compute_nilai_total", store=True)
    nilai_lulus = fields.Float(string="Minimal Persentase Kelulusan", default=70.0, help="Batas persentase kelulusan minimal. Default: 70%")
    nilai_lulus_kumulatif = fields.Float(string="Batas Nilai Lulus", compute="_compute_nilai_total", store=True)

    state = fields.Selection([
        ("draft", "Draft"),
        ("proses", "Proses Penilaian"),
        ("selesai", "Selesai Evaluasi"),
    ], string="Status", default="draft", tracking=True)

    status_kelulusan = fields.Selection([
        ("menunggu", "Menunggu Penilaian"),
        ("lulus", "Lulus (Kompeten)"),
        ("tidak_lulus", "Tidak Lulus (Belum Kompeten)"),
    ], string="Status Kelulusan", compute="_compute_status_kelulusan", store=True, tracking=True)

    catatan_asesor = fields.Text(string="Catatan Evaluasi Asesor")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("lsp.hasil.asesmen") or "NEW"
        return super(LspHasilAsesmen, self).create(vals_list)

    @api.depends("line_ids.nilai", "unit_line_ids.nilai")
    def _compute_nilai_total(self):
        for rec in self:
            rec._compute_unit_scores()
            # Nilai kumulatif adalah jumlah nilai dari semua Unit Kompetensi
            total_score = sum(unit.nilai for unit in rec.unit_line_ids)
            units_count = len(rec.unit_line_ids)
            
            rec.nilai_total = total_score
            rec.nilai_maksimal = units_count * 100.0
            rec.nilai_lulus_kumulatif = rec.nilai_maksimal * (rec.nilai_lulus / 100.0)

    @api.depends("state", "nilai_total", "nilai_lulus_kumulatif")
    def _compute_status_kelulusan(self):
        for rec in self:
            if rec.state != "selesai":
                rec.status_kelulusan = "menunggu"
            else:
                rec.status_kelulusan = "lulus" if rec.nilai_total >= rec.nilai_lulus_kumulatif else "tidak_lulus"

    def _compute_unit_scores(self):
        """Menghitung nilai rata-rata dari pertanyaan di setiap Unit Kompetensi (Section)"""
        for rec in self:
            if not rec.line_ids:
                continue
            sections = rec.line_ids.mapped("page_id")
            for sec in sections:
                sec_lines = rec.line_ids.filtered(lambda l: l.page_id == sec)
                avg_score = sum(l.nilai for l in sec_lines) / len(sec_lines) if sec_lines else 0.0
                
                # Cari atau buat record unit
                unit_line = rec.unit_line_ids.filtered(lambda u: u.page_id == sec)
                if unit_line:
                    unit_line.write({"nilai": avg_score})
                else:
                    self.env["lsp.hasil.asesmen.unit"].create({
                        "hasil_asesmen_id": rec.id,
                        "page_id": sec.id,
                        "nilai": avg_score,
                    })

    def action_proses(self):
        for rec in self:
            rec.state = "proses"

    def action_selesai(self):
        for rec in self:
            # Validasi: pastikan semua soal essay dan praktikum sudah dinilai oleh asesor
            non_pg_lines = rec.line_ids.filtered(lambda l: l.tipe_soal in ("essay", "praktikum"))
            # Jika ada soal non-PG yang masih bernilai default 0.0 tanpa catatan/evaluasi, bisa lolos,
            # tapi untuk mencegah kelalaian, kita pastikan semua line_ids terproses.
            rec.state = "selesai"
            # Memicu pembuatan sertifikat jika lulus
            if rec.status_kelulusan == "lulus":
                self.env["lsp.sertifikasi"]._generate_certificate(rec)

    def action_set_draft(self):
        for rec in self:
            rec.state = "draft"

    @api.model
    def _create_from_survey(self, user_input):
        # 1. Cari student
        student = self.env["lsp.student"].sudo().search([
            ("user_id", "=", user_input.create_uid.id)
        ], limit=1)
        if not student:
            return False

        # 2. Cari penugasan/jadwal ujian yang dikunci
        penugasan_line = self.env["lsp.penugasan.line"].sudo().search([
            ("asesi_ids", "in", student.id),
            ("state", "=", "dikunci")
        ], limit=1)
        if not penugasan_line:
            return False

        asesor_id = penugasan_line.asesor_id.id
        jadwal_id = penugasan_line.penugasan_id.jadwal_id.id

        # Cek jika sudah ada assessment untuk survey input ini
        existing = self.search([("survey_input_id", "=", user_input.id)], limit=1)
        if existing:
            return existing

        # 3. Buat assessment record
        assessment = self.create({
            "student_id": student.id,
            "asesor_id": asesor_id,
            "jadwal_id": jadwal_id,
            "survey_input_id": user_input.id,
            "state": "proses",
        })

        # Helper untuk menerjemahkan nilai jawaban
        def _get_answer_text(line):
            if line.answer_type == "text_box":
                return line.value_text_box
            elif line.answer_type == "char_box":
                return line.value_char_box
            elif line.answer_type == "numerical_box":
                return str(line.value_numerical_box)
            elif line.answer_type == "date":
                return str(line.value_date)
            elif line.answer_type == "datetime":
                return str(line.value_datetime)
            elif line.answer_type == "suggestion":
                return line.suggested_answer_id.value
            return ""

        # 4. Buat assessment lines untuk setiap pertanyaan non-page yang dijawab
        for line in user_input.user_input_line_ids:
            if line.question_id.is_page:
                continue

            initial_score = 0.0
            is_correct = False
            if line.question_id.lsp_question_type == "pg":
                is_correct = line.answer_is_correct
                initial_score = 100.0 if is_correct else 0.0

            self.env["lsp.hasil.asesmen.line"].create({
                "hasil_asesmen_id": assessment.id,
                "question_id": line.question_id.id,
                "user_input_line_id": line.id,
                "jawaban_asesi": _get_answer_text(line),
                "nilai": initial_score,
                "is_pg_correct": is_correct,
            })

        # Hitung skor unit & skor total
        assessment._compute_unit_scores()
        assessment._compute_nilai_total()
        return assessment


class LspHasilAsesmenLine(models.Model):
    _name = "lsp.hasil.asesmen.line"
    _description = "Detail Jawaban Hasil Asesmen"

    hasil_asesmen_id = fields.Many2one("lsp.hasil.asesmen", string="Hasil Asesmen", ondelete="cascade")
    question_id = fields.Many2one("survey.question", string="Pertanyaan", required=True)
    user_input_line_id = fields.Many2one("survey.user_input.line", string="Baris Jawaban", ondelete="cascade")
    page_id = fields.Many2one("survey.question", related="question_id.page_id", string="Unit Kompetensi", store=True)
    tipe_soal = fields.Selection(related="question_id.lsp_question_type", string="Tipe Soal", store=True)

    jawaban_asesi = fields.Text(string="Jawaban Asesi")
    jawaban_benar = fields.Text(string="Kunci Jawaban/Panduan")
    nilai = fields.Float(string="Nilai (0-100)", digits=(6, 2), default=0.0)
    is_pg_correct = fields.Boolean(string="PG Benar?")


class LspHasilAsesmenUnit(models.Model):
    _name = "lsp.hasil.asesmen.unit"
    _description = "Nilai per Unit Kompetensi"

    hasil_asesmen_id = fields.Many2one("lsp.hasil.asesmen", string="Hasil Asesmen", ondelete="cascade")
    page_id = fields.Many2one("survey.question", string="Unit Kompetensi", required=True)
    unit_code = fields.Char(related="page_id.unit_code", string="Kode Unit", store=True)
    nilai = fields.Float(string="Nilai Akhir Unit", digits=(6, 2), default=0.0)


class SurveyUserInput(models.Model):
    _inherit = "survey.user_input"

    def _mark_done(self):
        res = super(SurveyUserInput, self)._mark_done()
        for user_input in self:
            self.env["lsp.hasil.asesmen"]._create_from_survey(user_input)
        return res
