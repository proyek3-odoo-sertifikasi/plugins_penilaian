{
    "name": "LSP - Hasil Asesmen",
    "summary": "Manajemen hasil asesmen (nilai PG, essay, praktik) untuk LSP",
    "version": "19.0.1.0.0",
    "category": "LSP",
    "author": "Auto Generated",
    "website": "",
    "depends": ["base", "mail", "survey", "plugins_manajement_asesor", "plugins_lsp_survey"],
    "data": [
        "security/ir.model.access.csv",
        "security/lsp_penilaian_rules.xml",
        "data/ir_sequence_data.xml",
        "views/hasil_asesmen_views.xml",
        "views/lsp_menus.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
