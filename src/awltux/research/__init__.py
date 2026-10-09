"""Deep-dive research: one report per explicit request, stored on disk and in the database.

Four concerns, one module each:

* :mod:`awltux.research.report` -- turning a model's answer into a validated result set, and
  rendering it as the XHTML document that is kept.
* :mod:`awltux.research.evidence` -- gathering what the run reads: the held annual reports,
  the decision's own evidence, and the news digest.
* :mod:`awltux.research.service` -- the background job: refresh the subject, gather, ask,
  write.

Nothing here schedules itself. A report costs a pipeline refresh plus one deep model call, so
the only trigger is a reader pressing the button on the subject's page.
"""
