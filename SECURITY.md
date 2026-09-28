# Security

**What the index holds.** Structure, not text: names, kinds, line ranges, relations, and a
content hash per file. Source is never copied into the database; `read_source` reads the
file from disk at call time. Symbol names still describe a design, so treat an index as
you would treat the repository it was built from.

**What leaves the machine.** Nothing, by default. The optional model tier sends file
contents to the endpoint you configure, only for files no parser could read, only when
`SKYGRAPH_MODEL_KEY` is set, and never more than the budget. The key is read from the
environment and is not written into the index or the run report.

**What the server can do.** Fourteen tools, all read-only. There is no write tool;
indexing is a separate command. The server listens on stdio only.

**Reporting.** Open a private security advisory on the GitHub repository. Please do not
open a public issue for a vulnerability.
