export default function DashboardPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">
          Dashboard
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          Overview of monthly grocery &amp; household spending, active budgets,
          recent receipts, and cached AI insights.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: "Monthly Spending", value: "0.00 RON" },
          { label: "Food Spending", value: "0.00 RON" },
          { label: "Household Spending", value: "0.00 RON" },
          { label: "Active Budgets", value: "0" },
        ].map((card) => (
          <div
            key={card.label}
            className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs"
          >
            <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">
              {card.label}
            </p>
            <p className="mt-2 text-2xl font-semibold text-slate-900">
              {card.value}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
