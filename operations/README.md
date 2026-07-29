# Operations

Procedures for running the demonstration. Deliberately narrow: this is not
incident management, backup, disaster recovery, or monitoring. Those are not part
of the first working KAE demonstration and building them now would be
speculative.

```text
operations/
├── README.md
└── runbooks/
    ├── deploy-first-demo.md
    ├── restart-services.md
    └── worker-recovery-demo.md
```

## The runbook that matters

[`runbooks/worker-recovery-demo.md`](runbooks/worker-recovery-demo.md) is the
central one. Durable continuation is KAE's core claim, and AT-009 is how it is
proven: kill the worker, let the lease expire, let the supervisor restart it,
and watch the run reclaim itself and finish exactly once — with no manual repair
and no duplicated output.

It is written now, ahead of deployment, because the protocol it describes is
**already implemented and already tested**. What is missing is the process
wrapper, not the recovery.
